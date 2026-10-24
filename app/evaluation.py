"""Phase 4: the evaluation set and how we decide a retrieved chunk is "correct".

A chunk counts as relevant to a question when it comes from the right grant
AND contains the question's evidence quote. Matching on the quote (instead of
a fixed chunk id) means the same exam works for every chunking strategy, so
section vs. fixed chunking can be compared fairly.
"""

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "eval" / "questions.csv"


@dataclass
class Question:
    id: str
    type: str  # "answerable" | "unanswerable"
    category: str
    question: str
    opportunity_id: int | None
    evidence: str
    answer: str
    status: str


def normalize(text: str) -> str:
    """Lowercase and keep only letters/digits, so quotes match despite
    punctuation, bullets, curly quotes, or line-break differences. NFKC turns
    ligatures like "ﬁ" (common in PDFs) into plain "fi"."""
    text = unicodedata.normalize("NFKC", text).lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def load_questions(include_drafts: bool = True) -> list[Question]:
    with QUESTIONS.open(newline="") as f:
        rows = list(csv.DictReader(f))
    questions = [
        Question(
            id=r["id"],
            type=r["type"],
            category=r["category"],
            question=r["question"],
            opportunity_id=int(r["opportunity_id"]) if r["opportunity_id"] else None,
            evidence=r["evidence"],
            answer=r["answer"],
            status=r["status"].strip().lower(),
        )
        for r in rows
    ]
    allowed = {"keep", "draft"} if include_drafts else {"keep"}
    return [q for q in questions if q.status in allowed]


def find_quote_page(pdf_path: Path, quote: str) -> int | None:
    """Physical page (1 = first page, as Chrome's page box counts) where the
    quote appears. Checks page pairs too, for quotes split across a page break.

    Note: this is not the number printed on the page. Most NOFOs don't
    number the cover, so printed "Page 4 of 20" is often physical page 5.
    """
    import fitz

    target = normalize(quote)
    if not target:
        return None
    with fitz.open(pdf_path) as doc:
        raw_pages = [page.get_text() for page in doc]
    # Words hyphenated across a line break ("uni-\nversities") are joined in
    # chunks, so try each page both as printed and with those breaks joined.
    variants = [
        [normalize(t) for t in raw_pages],
        [normalize(re.sub(r"-\s*\n\s*", "", t)) for t in raw_pages],
    ]
    for pages in variants:
        for i, text in enumerate(pages):
            if target in text:
                return i + 1
    for pages in variants:
        for i in range(len(pages) - 1):
            if target in pages[i] + " " + pages[i + 1]:
                return i + 1
    return None


def is_relevant(chunk: dict, q: Question) -> bool:
    if q.opportunity_id is None or chunk["opportunity_id"] != q.opportunity_id:
        return False
    if not q.evidence:  # "discovery" questions: finding the right grant is enough
        return True
    haystack = normalize((chunk.get("section") or "") + " " + chunk["text"])
    return normalize(q.evidence) in haystack
