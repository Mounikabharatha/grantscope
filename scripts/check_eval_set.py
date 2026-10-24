"""Phase 4: sanity-check eval/questions.csv before trusting any score.

For every answerable question, confirm its evidence quote really exists in at
least one chunk of the right grant, in every chunk set we compare. A question
whose evidence can't be found would silently count as a retrieval miss.

Also checks each question's page number against where the quote really is
in the PDF (Chrome's page count, not the number printed on the page).

Usage:
  python scripts/check_eval_set.py
  python scripts/check_eval_set.py --fix-pages   # rewrite wrong page numbers
"""

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.evaluation import QUESTIONS, find_quote_page, is_relevant, load_questions  # noqa: E402

CHUNK_SETS = ["section_300", "fixed_300"]


def check_pages(fix: bool) -> int:
    with QUESTIONS.open(newline="") as f:
        reader = csv.DictReader(f)
        fieldnames, rows = reader.fieldnames, list(reader)
    wrong = 0
    for row in rows:
        if row["type"] != "answerable" or not row["evidence"]:
            continue
        page = find_quote_page(ROOT / "data" / "raw" / f"{row['opportunity_id']}.pdf", row["evidence"])
        if page is None:
            wrong += 1
            print(f"  QUOTE NOT IN PDF {row['id']}: {row['evidence']!r}")
        elif str(page) != row["page"]:
            print(f"  PAGE {row['id']}: listed {row['page'] or '?'}, quote is on page {page}" + (" (fixed)" if fix else ""))
            if fix:
                row["page"] = str(page)
            else:
                wrong += 1
    if fix:
        with QUESTIONS.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    print(f"\n[pages] {'fixed' if fix else 'checked'} page numbers against the PDFs")
    return wrong


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix-pages", action="store_true")
    args = parser.parse_args()
    questions = load_questions()
    answerable = [q for q in questions if q.type == "answerable"]
    print(f"{len(questions)} questions: {len(answerable)} answerable, "
          f"{len(questions) - len(answerable)} unanswerable")
    print("Categories:", dict(Counter(q.category for q in questions)))

    problems = 0
    for chunk_set in CHUNK_SETS:
        chunks = [json.loads(line) for line in (ROOT / "data" / "chunks" / f"{chunk_set}.jsonl").open()]
        by_grant: dict[int, list[dict]] = {}
        for c in chunks:
            by_grant.setdefault(c["opportunity_id"], []).append(c)

        missing = [q for q in answerable
                   if not any(is_relevant(c, q) for c in by_grant.get(q.opportunity_id, []))]
        relevant_counts = [sum(is_relevant(c, q) for c in by_grant.get(q.opportunity_id, []))
                           for q in answerable if q.evidence]
        print(f"\n[{chunk_set}] evidence found for {len(answerable) - len(missing)}/{len(answerable)}")
        if relevant_counts:
            print(f"  relevant chunks per question: min {min(relevant_counts)}, max {max(relevant_counts)}")
        for q in missing:
            problems += 1
            print(f"  MISSING {q.id}: {q.evidence!r} (grant {q.opportunity_id})")

    problems += check_pages(fix=args.fix_pages)
    print("\nOK: every evidence quote was found on its page." if not problems else f"\n{problems} problem(s) to fix.")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
