"""Phase 4: the evaluation set and how we decide a retrieved chunk is "correct".

A chunk counts as relevant to a question when it comes from the right grant
AND contains the question's evidence quote. Matching on the quote (instead of
a fixed chunk id) means the same exam works for every chunking strategy, so
section vs. fixed chunking can be compared fairly.
"""

import csv
import re
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
    punctuation, bullets, curly quotes, or line-break differences."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


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


def is_relevant(chunk: dict, q: Question) -> bool:
    if q.opportunity_id is None or chunk["opportunity_id"] != q.opportunity_id:
        return False
    if not q.evidence:  # "discovery" questions: finding the right grant is enough
        return True
    haystack = normalize((chunk.get("section") or "") + " " + chunk["text"])
    return normalize(q.evidence) in haystack
