"""Phase 6: score generated answers on the evaluation set.

  refusal accuracy  - unanswerable questions the system correctly declined
  answer rate       - answerable questions it answered (the rest are false refusals)
  correctness       - answered questions whose answer matches the reference answer
                      (LLM judge: correct / partial / incorrect)
  faithfulness      - answered questions where every claim is supported by the
                      answer's own verified quotes (LLM judge)
  quote validity    - of all quotes the LLM produced, the share found word-for-word
                      in the passage they cite (deterministic string check; invalid
                      quotes are dropped before the user sees the answer)

The judge is the same local Llama 3.1 8B, at temperature 0. A small model is an
imperfect judge, so its verdicts should be spot-checked by hand.

Usage:
  python scripts/evaluate_answers.py               # all 93 questions (~15-25 min locally)
  python scripts/evaluate_answers.py --limit 10    # quick check
  python scripts/evaluate_answers.py --ids q022 q081
"""

import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.answer import MIN_RERANK_SCORE, answer_question  # noqa: E402
from app.embeddings import get_model  # noqa: E402
from app.evaluation import load_questions  # noqa: E402
from app.llm import MODEL, chat, parse_json  # noqa: E402
from app.search import get_reranker  # noqa: E402

CORRECTNESS_PROMPT = """You grade answers to questions about grant funding announcements.

Question: {question}
Reference answer (known to be correct): {reference}
System answer: {answer}

Compare the system answer to the reference answer.
- "correct": it states the same key fact(s) as the reference. Different wording is fine; extra correct detail is fine.
- "partial": it gets part of the key fact right but misses or blurs an important part.
- "incorrect": it states a different or wrong fact, or doesn't answer the question.

Respond with JSON only: {{"verdict": "correct" | "partial" | "incorrect", "reason": "one short sentence"}}"""

FAITHFULNESS_PROMPT = """You check whether an answer is supported by its sources.

Quotes from the source documents:
{quotes}

Answer: {answer}

Is every factual claim in the answer stated in, or directly implied by, the quotes above?
Ignore wording differences. Naming the grant the quotes come from is fine.

Respond with JSON only: {{"supported": true | false, "unsupported_claim": "the first claim not backed by the quotes, or empty"}}"""


def judge(prompt: str) -> dict:
    try:
        return parse_json(chat([{"role": "user", "content": prompt}], max_tokens=200))
    except Exception as exc:  # a judge failure shouldn't stop the whole run
        return {"error": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--label", default="answers")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    questions = load_questions()
    if args.ids:
        questions = [q for q in questions if q.id in set(args.ids)]
    if args.limit:
        # Keep the mix: some answerable and some unanswerable questions.
        ans = [q for q in questions if q.type == "answerable"]
        una = [q for q in questions if q.type == "unanswerable"]
        n_una = max(1, args.limit // 5)
        questions = ans[: args.limit - n_una] + una[:n_una]
    print(f"Answering {len(questions)} questions with {MODEL}...")
    get_model(), get_reranker()

    records = []
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for i, q in enumerate(questions, 1):
            start = time.perf_counter()
            a = answer_question(conn, q.question)
            total_ms = round((time.perf_counter() - start) * 1000)
            rec = {
                "id": q.id, "type": q.type, "category": q.category, "question": q.question,
                "reference": q.answer, "answer": a.answer, "refused": a.refused,
                "refusal_reason": a.refusal_reason, "top_score": a.top_score,
                "citations": [c.__dict__ for c in a.citations],
                "dropped_citations": [c.__dict__ for c in a.dropped_citations],
                "timings_ms": {**a.timings_ms, "total": total_ms},
            }
            if q.type == "answerable" and not a.refused:
                rec["correctness"] = judge(CORRECTNESS_PROMPT.format(
                    question=q.question, reference=q.answer, answer=a.answer))
                # Give the judge each quote's grant and section heading, as a human checker would see them
                # (e.g. a list item quoted from a "Funding Restrictions" section).
                quotes = "\n".join(f'- "{c.quote}" (grant: {c.title}; section: {c.section or "n/a"})'
                                    for c in a.citations)
                rec["faithfulness"] = judge(FAITHFULNESS_PROMPT.format(quotes=quotes, answer=a.answer))
            records.append(rec)

            status = "REFUSED " + (a.refusal_reason or "") if a.refused else \
                rec.get("correctness", {}).get("verdict", "answered")
            print(f"  [{i}/{len(questions)}] {q.id} {q.type[:5]:<6} {status:<24} {total_ms / 1000:5.1f}s  {q.question[:60]}",
                  flush=True)

    report(records)
    out = ROOT / "eval" / "results" / f"{date.today()}_{args.label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": MODEL, "min_rerank_score": MIN_RERANK_SCORE, "records": records},
                              indent=2, default=str))
    print(f"\nSaved to {out.relative_to(ROOT)}")


def pct(n: int, d: int) -> str:
    return f"{n / d:.1%} ({n}/{d})" if d else "n/a"


def report(records: list[dict]) -> None:
    ans = [r for r in records if r["type"] == "answerable"]
    una = [r for r in records if r["type"] == "unanswerable"]
    answered = [r for r in ans if not r["refused"]]
    verdicts = Counter(r.get("correctness", {}).get("verdict", "judge_error") for r in answered)
    supported = sum(1 for r in answered if r.get("faithfulness", {}).get("supported") is True)
    n_quotes = sum(len(r["citations"]) + len(r["dropped_citations"]) for r in records)
    n_valid = sum(len(r["citations"]) for r in records)
    any_dropped = sum(1 for r in answered if r["dropped_citations"])

    print("\n===== Answer quality =====")
    print(f"Unanswerable correctly refused : {pct(sum(r['refused'] for r in una), len(una))}")
    print(f"Answerable answered            : {pct(len(answered), len(ans))}")
    print(f"  false refusals by reason     : {dict(Counter(r['refusal_reason'] for r in ans if r['refused']))}")
    print(f"Correct (of answered)          : {pct(verdicts['correct'], len(answered))}"
          f"   partial {verdicts['partial']}, incorrect {verdicts['incorrect']}, judge errors {verdicts['judge_error']}")
    print(f"Correct (of all answerable)    : {pct(verdicts['correct'], len(ans))}")
    print(f"Faithfulness (of answered)     : {pct(supported, len(answered))}")
    print(f"Quote validity (all quotes)    : {pct(n_valid, n_quotes)}")
    print(f"Answers that had a quote dropped: {any_dropped}")
    gen = [r["timings_ms"].get("generation") for r in records if r["timings_ms"].get("generation")]
    tot = [r["timings_ms"]["total"] for r in records]
    if tot:
        print(f"Latency total  median {statistics.median(tot) / 1000:.1f}s, max {max(tot) / 1000:.1f}s"
              + (f" | generation median {statistics.median(gen) / 1000:.1f}s" if gen else ""))

    print("\nUnanswerable questions that got an answer:")
    for r in una:
        if not r["refused"]:
            print(f"  {r['id']}: {r['question'][:70]}\n      -> {r['answer'][:150]}")
    print("\nAnswered but judged incorrect/partial or unsupported:")
    for r in answered:
        v = r.get("correctness", {}).get("verdict")
        if v != "correct" or r.get("faithfulness", {}).get("supported") is not True:
            print(f"  {r['id']} [{v}, supported={r.get('faithfulness', {}).get('supported')}] {r['question'][:70]}")
            print(f"      expected: {r['reference'][:100]}\n      got:      {r['answer'][:150]}")


if __name__ == "__main__":
    main()
