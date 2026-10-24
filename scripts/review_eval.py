"""Phase 4: review eval/questions.csv one question at a time.

For each question still marked "draft" it shows the question, the expected
answer, and the evidence quote in context, opens the PDF at the right page in
Chrome, and saves your decision straight into the CSV.

Usage:
  python scripts/review_eval.py              # continue with the next draft question
  python scripts/review_eval.py --sample 20  # a fair random spot-check instead of all
  python scripts/review_eval.py --no-pdf     # don't open PDFs

Tip: in the PDF, press Cmd+F and type a few words of the QUOTE to jump to it.

Keys:  k = keep   f = fix (asks for a note)   d = delete   s = skip   q = quit
"""

import argparse
import csv
import json
import random
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.evaluation import QUESTIONS, normalize  # noqa: E402

CHUNKS = ROOT / "data" / "chunks" / "section_300.jsonl"


def evidence_in_context(rows_chunks: list[dict], evidence: str) -> str | None:
    """Return ~250 characters of the PDF text around the evidence quote."""
    target = normalize(evidence)
    for c in rows_chunks:
        text = c["text"]
        if target and target in normalize((c["section"] or "") + " " + text):
            # Locate the quote itself (not just its first word, which may also
            # appear earlier): try the whole quote, then shorter openings.
            words, lower, start = evidence.split(), text.lower(), -1
            for n in (len(words), 6, 4, 2):
                start = lower.find(" ".join(words[:n]).lower())
                if start >= 0:
                    break
            if start < 0:
                return text[:300]
            return ("…" if start > 120 else "") + text[max(0, start - 120): start + len(evidence) + 130] + "…"
    return None


def spread_sample(todo: list[dict], size: int, already_reviewed: int) -> list[dict]:
    """A fixed random sample (same every run, so you can quit and resume)
    that takes questions from every agency plus some unanswerable ones."""
    import json as _json
    agency = {str(d["opportunity_id"]): d["agency_code"]
              for d in map(_json.loads, (ROOT / "data" / "metadata.jsonl").open())}
    groups: dict[str, list[dict]] = {}
    for row in todo:
        key = agency.get(row["opportunity_id"], "unanswerable")
        groups.setdefault(key, []).append(row)
    rng = random.Random(42)
    for rows in groups.values():
        rng.shuffle(rows)
    picked: list[dict] = []
    target = max(0, size - already_reviewed)
    while len(picked) < target and any(groups.values()):
        for rows in groups.values():  # round-robin across agencies
            if rows and len(picked) < target:
                picked.append(rows.pop())
    return sorted(picked, key=lambda r: r["id"])


def open_pdf(opportunity_id: str, page: str) -> None:
    pdf = ROOT / "data" / "raw" / f"{opportunity_id}.pdf"
    url = pdf.as_uri() + (f"#page={page}" if page else "")
    subprocess.run(["open", "-a", "Google Chrome", url], check=False)


def save(rows: list[dict], fieldnames: list[str]) -> None:
    with QUESTIONS.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-pdf", action="store_true")
    parser.add_argument("--sample", type=int, help="spot-check this many questions, spread across agencies")
    args = parser.parse_args()

    with QUESTIONS.open(newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    chunks_by_grant: dict[str, list[dict]] = {}
    for line in CHUNKS.open():
        c = json.loads(line)
        chunks_by_grant.setdefault(str(c["opportunity_id"]), []).append(c)

    todo = [r for r in rows if r["status"].strip().lower() == "draft"]
    done = len(rows) - len(todo)
    total = len(rows)
    if args.sample:
        todo = spread_sample(todo, args.sample, already_reviewed=done)
        total = max(args.sample, done)
    print(f"{done}/{total} reviewed. {len(todo)} to go.")
    print("For each question: read it, Cmd+F the QUOTE in the PDF, ask 'does this answer the question?'\n")

    for n, row in enumerate(todo, start=done + 1):
        wrap = lambda s: textwrap.fill(s, 100, subsequent_indent="    ")
        print("=" * 100)
        print(f"[{n}/{total}] {row['id']}  ({row['type']}, {row['category']})")
        print(wrap(f"QUESTION: {row['question']}"))
        if row["type"] == "answerable":
            print(wrap(f"GRANT:    {row['grant']}"))
            print(f"PAGE:     {row['page'] or '?'} of the PDF file (the box at the top of Chrome, e.g. \"{row['page'] or '?'} / 33\"). "
                  "The number printed on the page itself can be lower; ignore it.")
            print(wrap(f"ANSWER:   {row['answer']}"))
            if row["evidence"]:
                print(wrap(f"QUOTE:    \"{row['evidence']}\""))
                context = evidence_in_context(chunks_by_grant.get(row["opportunity_id"], []), row["evidence"])
                print(wrap(f"IN PDF:   {context}") if context else "IN PDF:   (quote not found! mark as fix)")
            if not args.no_pdf:
                open_pdf(row["opportunity_id"], row["page"])
        else:
            print("CHECK:    Is it true that none of our 200 grants answers this? (It should be refused.)")

        while True:
            choice = input("\n[k]eep  [f]ix  [d]elete  [s]kip  [q]uit > ").strip().lower()
            if choice in {"k", "f", "d", "s", "q"}:
                break
        if choice == "q":
            break
        if choice == "s":
            continue
        row["status"] = {"k": "keep", "f": "fix", "d": "delete"}[choice]
        if choice in {"f", "d"}:
            row["reviewer_notes"] = input("What's wrong? > ").strip()
        save(rows, fieldnames)  # save after every answer, so quitting never loses work

    remaining = sum(r["status"].strip().lower() == "draft" for r in rows)
    print(f"\nSaved. {len(rows) - remaining}/{len(rows)} reviewed, {remaining} left.")


if __name__ == "__main__":
    main()
