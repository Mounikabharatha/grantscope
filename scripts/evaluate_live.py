"""Phase 8: run the evaluation against the deployed site, through its public API.

Same questions and scoring as the local evals, so the live numbers are directly comparable:
  retrieval  GET /search?method=...&k=20  -> recall@k, MRR, right grant in top 5
  answers    GET /ask                     -> refusals, answer rate, quote validity, and
                                             correctness/faithfulness judged by the local
                                             Llama 3.1 8B (Ollama), as in evaluate_answers.py

Each /ask uses Workers AI, which has a free daily allowance; a full answer run (93 questions)
fits in it, but don't run it many times a day.

Usage:
  python scripts/evaluate_live.py --base-url https://grantscope.mounikabharatha.workers.dev
  python scripts/evaluate_live.py --base-url ... --skip-answers
"""

import argparse
import json
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.evaluation import is_relevant, load_questions  # noqa: E402
from evaluate_answers import CORRECTNESS_PROMPT, FAITHFULNESS_PROMPT, judge, report  # noqa: E402

KS = [1, 3, 5, 10, 20]


def get(base: str, path: str, params: dict, retries: int = 3) -> dict:
    for attempt in range(retries):
        resp = requests.get(f"{base}{path}", params=params, timeout=180)
        if resp.status_code == 200:
            return resp.json()
        time.sleep(2 * (attempt + 1))
    resp.raise_for_status()
    return {}


def eval_retrieval(base: str, questions, method: str) -> dict:
    ranks, latencies = [], []
    for q in questions:
        start = time.perf_counter()
        hits = get(base, "/search", {"q": q.question, "k": max(KS), "method": method})["results"]
        latencies.append((time.perf_counter() - start) * 1000)
        rank = next((i for i, h in enumerate(hits, 1) if is_relevant(h, q)), None)
        grant = next((i for i, h in enumerate(hits, 1) if h["opportunity_id"] == q.opportunity_id), None)
        ranks.append((q.id, rank, grant))
    n = len(ranks)
    return {
        "method": method,
        "n_questions": n,
        "recall": {k: sum(1 for _, r, _ in ranks if r and r <= k) / n for k in KS},
        "mrr": sum(1 / r for _, r, _ in ranks if r) / n,
        "grant_at_5": sum(1 for _, _, g in ranks if g and g <= 5) / n,
        "latency_ms": {"median": statistics.median(latencies), "p95": sorted(latencies)[int(0.95 * n) - 1]},
        "misses_at_5": [qid for qid, r, _ in ranks if not (r and r <= 5)],
    }


def eval_answers(base: str, questions) -> list[dict]:
    records = []
    for i, q in enumerate(questions, 1):
        start = time.perf_counter()
        a = get(base, "/ask", {"q": q.question})
        total_ms = round((time.perf_counter() - start) * 1000)
        rec = {
            "id": q.id, "type": q.type, "category": q.category, "question": q.question,
            "reference": q.answer, "answer": a["answer"], "refused": a["refused"],
            "refusal_reason": a["refusal_reason"], "top_score": a["top_score"],
            "citations": a["citations"], "dropped_citations": a["dropped_citations"],
            "timings_ms": {**a["timings_ms"], "total": total_ms}, "model": a["model"],
        }
        if q.type == "answerable" and not a["refused"]:
            rec["correctness"] = judge(CORRECTNESS_PROMPT.format(question=q.question, reference=q.answer, answer=a["answer"]))
            quotes = "\n".join(f'- "{c["quote"]}" (grant: {c["title"]}; section: {c.get("section") or "n/a"})'
                               for c in a["citations"])
            rec["faithfulness"] = judge(FAITHFULNESS_PROMPT.format(quotes=quotes, answer=a["answer"]))
        records.append(rec)
        status = f"REFUSED {a['refusal_reason']}" if a["refused"] else rec.get("correctness", {}).get("verdict", "answered")
        print(f"  [{i}/{len(questions)}] {q.id} {q.type[:5]:<6} {status:<24} {total_ms / 1000:5.1f}s  {q.question[:60]}",
              flush=True)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--methods", nargs="+", default=["vector", "hybrid_rerank"])
    parser.add_argument("--skip-answers", action="store_true")
    parser.add_argument("--skip-retrieval", action="store_true")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("Health:", get(base, "/health", {}))
    questions = load_questions()
    out: dict = {"base_url": base, "date": str(date.today())}

    if not args.skip_retrieval:
        answerable = [q for q in questions if q.type == "answerable"]
        print(f"\nRetrieval on the live site ({len(answerable)} questions)...")
        out["retrieval"] = []
        for method in args.methods:
            r = eval_retrieval(base, answerable, method)
            out["retrieval"].append(r)
            print(f"  {method:<14} R@1 {r['recall'][1]:.1%}  R@5 {r['recall'][5]:.1%}  R@10 {r['recall'][10]:.1%}  "
                  f"MRR {r['mrr']:.3f}  grant@5 {r['grant_at_5']:.1%}  median {r['latency_ms']['median']:.0f} ms")

    if not args.skip_answers:
        print(f"\nAnswers on the live site ({len(questions)} questions)...")
        out["answers"] = eval_answers(base, questions)
        report(out["answers"])

    path = ROOT / "eval" / "results" / f"{date.today()}_live.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nSaved to {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
