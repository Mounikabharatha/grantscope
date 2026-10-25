"""Phase 4/5: score retrieval on the evaluation set.

For each answerable question, run the search and check whether a relevant
chunk (right grant + contains the evidence quote) is in the top k results.

  recall@k  - share of questions with a relevant chunk in the top k
              (each question has one fact to find, so this equals hit rate@k)
  MRR       - mean of 1/rank of the first relevant chunk (0 if not in top 20);
              rewards putting the answer first, not just somewhere in the top 5
  grant@5   - share of questions where the right grant appears in the top 5,
              even if the exact passage doesn't

Usage:
  python scripts/evaluate_retrieval.py                                  # all methods, both chunk sets
  python scripts/evaluate_retrieval.py --methods vector hybrid --chunk-sets section_300
  python scripts/evaluate_retrieval.py --chunk-sets section_300 --methods vector hybrid_rerank \
      --min-recall5 vector=0.79 hybrid_rerank=0.87     # CI quality gate: exit 1 if below
"""

import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.embeddings import get_model  # noqa: E402
from app.evaluation import QUESTIONS, is_relevant, load_questions  # noqa: E402
from app.search import METHODS, search  # noqa: E402

KS = [1, 3, 5, 10, 20]
RESULTS_DIR = ROOT / "eval" / "results"


def evaluate(conn, questions, chunk_set: str, method: str) -> dict:
    per_question = []
    latencies = []
    for q in questions:
        start = time.perf_counter()
        hits = search(conn, q.question, chunk_set, max(KS), method=method)
        latencies.append((time.perf_counter() - start) * 1000)
        rank = next((i for i, h in enumerate(hits, 1) if is_relevant(h, q)), None)
        grant_rank = next((i for i, h in enumerate(hits, 1) if h["opportunity_id"] == q.opportunity_id), None)
        per_question.append({
            "id": q.id, "category": q.category, "question": q.question,
            "rank": rank, "grant_rank": grant_rank,
            "top1": {"grant": hits[0]["title"][:80], "section": hits[0]["section"]} if hits else None,
        })

    n = len(per_question)
    recall = {k: sum(1 for r in per_question if r["rank"] and r["rank"] <= k) / n for k in KS}
    by_category = defaultdict(list)
    for r in per_question:
        by_category[r["category"]].append(bool(r["rank"] and r["rank"] <= 5))
    return {
        "chunk_set": chunk_set,
        "method": method,
        "name": f"{chunk_set}/{method}",
        "n_questions": n,
        "recall": recall,
        "mrr": sum(1 / r["rank"] for r in per_question if r["rank"]) / n,
        "grant_at_5": sum(1 for r in per_question if r["grant_rank"] and r["grant_rank"] <= 5) / n,
        "recall5_by_category": {c: (sum(v) / len(v), len(v)) for c, v in sorted(by_category.items())},
        "latency_ms": {"median": statistics.median(latencies), "p95": sorted(latencies)[int(0.95 * n) - 1]},
        "per_question": per_question,
    }


def print_report(results: list[dict]) -> None:
    print(f"\n{'setup':<28}" + "".join(f"{'R@' + str(k):>8}" for k in KS) + f"{'MRR':>8}{'grant@5':>9}{'median ms':>11}{'p95 ms':>9}")
    for r in results:
        print(f"{r['name']:<28}" + "".join(f"{r['recall'][k]:>8.1%}" for k in KS)
              + f"{r['mrr']:>8.3f}{r['grant_at_5']:>9.1%}{r['latency_ms']['median']:>11.1f}{r['latency_ms']['p95']:>9.1f}")

    print("\nRecall@5 by question category:")
    cats = sorted({c for r in results for c in r["recall5_by_category"]})
    print(f"  {'category':<14}{'n':>4}" + "".join(f"{r['name'].replace('section_300/', 'sec/').replace('fixed_300/', 'fix/'):>20}" for r in results))
    for c in cats:
        n = results[0]["recall5_by_category"].get(c, (0, 0))[1]
        print(f"  {c:<14}{n:>4}" + "".join(f"{r['recall5_by_category'].get(c, (0, 0))[0]:>20.0%}" for r in results))

    for r in results[-1:] if len(results) > 2 else results:  # misses for the last (usually best) setup
        misses = [q for q in r["per_question"] if not (q["rank"] and q["rank"] <= 5)]
        print(f"\n[{r['name']}] {len(misses)} misses at k=5:")
        for q in misses:
            where = f"found at rank {q['rank']}" if q["rank"] else "not in top 20"
            grant = f"grant at rank {q['grant_rank']}" if q["grant_rank"] else "grant not in top 20"
            print(f"  {q['id']} ({q['category']}, {where}, {grant}): {q['question'][:85]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chunk-sets", nargs="+", default=["section_300", "fixed_300"])
    parser.add_argument("--methods", nargs="+", default=METHODS, choices=METHODS)
    parser.add_argument("--questions", type=Path, default=QUESTIONS, help="e.g. eval/holdout.csv")
    parser.add_argument("--label", default="retrieval", help="name for the saved results file")
    parser.add_argument("--min-recall5", nargs="+", default=[], metavar="METHOD=VALUE",
                        help="fail (exit 1) if a method's recall@5 is below VALUE, e.g. hybrid_rerank=0.87")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    questions = [q for q in load_questions(path=args.questions) if q.type == "answerable"]
    print(f"Evaluating {len(questions)} answerable questions...")
    get_model()  # load once so latency numbers measure search, not model loading

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        results = [evaluate(conn, questions, cs, m) for cs in args.chunk_sets for m in args.methods]
    print_report(results)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{date.today()}_{args.label}.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nSaved full results to {out.relative_to(ROOT)}")

    failures = check_gates(results, args.min_recall5)
    write_github_summary(results, args.min_recall5, failures)
    if failures:
        print("\nQUALITY GATE FAILED:\n  " + "\n  ".join(failures))
        sys.exit(1)
    if args.min_recall5:
        print("\nQuality gate passed.")


def parse_gates(specs: list[str]) -> dict[str, float]:
    return {method: float(value) for method, value in (spec.split("=", 1) for spec in specs)}


def check_gates(results: list[dict], specs: list[str]) -> list[str]:
    failures = []
    for method, minimum in parse_gates(specs).items():
        for r in (r for r in results if r["method"] == method):
            if r["recall"][5] < minimum:
                failures.append(f"{r['name']}: recall@5 {r['recall'][5]:.1%} < required {minimum:.1%}")
    return failures


def write_github_summary(results: list[dict], specs: list[str], failures: list[str]) -> None:
    """In GitHub Actions, show a results table on the run's summary page."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    gates = parse_gates(specs)
    lines = [
        "## Retrieval evaluation",
        "",
        f"{results[0]['n_questions']} answerable questions from `eval/questions.csv`.",
        "",
        "| Setup | Recall@1 | Recall@5 | Recall@10 | MRR | Right grant in top 5 | Minimum R@5 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        gate = gates.get(r["method"])
        status = "" if gate is None else f"{gate:.0%} {'✅' if r['recall'][5] >= gate else '❌'}"
        lines.append(f"| {r['name']} | {r['recall'][1]:.1%} | {r['recall'][5]:.1%} | {r['recall'][10]:.1%} "
                     f"| {r['mrr']:.3f} | {r['grant_at_5']:.1%} | {status} |")
    lines += ["", "**Quality gate failed**" if failures else "**Quality gate passed**", ""]
    with open(path, "a") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
