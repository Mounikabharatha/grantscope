"""Phase 6: cited answers with quote verification and refusals.

  1. Retrieve the top passages (hybrid search + reranker).
  2. Refuse early if even the best passage is clearly irrelevant.
  3. Ask the LLM to answer ONLY from the numbered passages and to back every
     claim with a quote copied word-for-word, citing the passage number.
  4. Verify each quote really appears in the passage it cites. Unverifiable
     quotes are dropped; an answer with no verified quote is not shown, and
     the system says it couldn't find a supported answer instead.

MIN_RERANK_SCORE is a fixed, conservative cutoff picked before evaluation
(the reranker outputs 0-1 relevance; unrelated passages typically score near
0). It only catches clearly hopeless cases; the LLM's own "not answerable"
judgment and the quote check do the rest.
"""

import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psycopg

from app.evaluation import find_quote_page, normalize
from app.llm import MODEL, chat, parse_json
from app.scope import scope_question, scoped_filters
from app.search import Filters, search

ROOT = Path(__file__).resolve().parent.parent
MIN_RERANK_SCORE = 0.05
TOP_K = 5

SYSTEM_PROMPT = """You answer questions about U.S. federal grant funding announcements.

Use ONLY the numbered passages you are given. Never use outside knowledge.

Rules:
1. Every fact in your answer must be supported by a quote copied word-for-word from a passage.
2. Each quote must be short (under 40 words), copied exactly, and cite the passage number it came from.
3. If the passages do not clearly answer the question, or they are about a different grant or
   program than the one asked about, set "answerable" to false and leave "answer" empty.
4. Keep the answer short and direct (1-3 sentences). Name the grant you are answering about.

Respond with JSON only, in exactly this format:
{"answerable": true, "answer": "...", "citations": [{"passage": 1, "quote": "exact words from passage 1"}]}"""

# The model sometimes writes "this isn't in the passages" but still marks the
# answer as answerable and attaches an unrelated quote. Treat such text as a refusal.
NON_ANSWER_CLAIM = re.compile(
    r"\b(no|not|isn't|aren't|doesn't|don't)\b\W+(?:\w+\W+){0,3}?"
    r"(mention(ed)?|provided?|stated?|specif(y|ied|ies)|available|include[sd]?|found|says?)\b",
    re.I,
)
NON_ANSWER_SOURCE = re.compile(r"\b(passages?|documents?|context|provided text)\b", re.I)


def is_non_answer(text: str) -> bool:
    """True for text like "X is not mentioned in the passages" (a claim that
    something is missing AND a reference to the source), but not for real
    answers like "For-profit hospitals are not eligible"."""
    return bool(NON_ANSWER_CLAIM.search(text) and NON_ANSWER_SOURCE.search(text))


REFUSAL_NO_PASSAGES = "I couldn't find anything relevant to this question in the grant documents."
REFUSAL_NOT_ANSWERABLE = "The grant documents I found don't answer this question."
REFUSAL_UNVERIFIED = "I couldn't find a supported answer to this question in the grant documents."


@dataclass
class Citation:
    passage: int
    quote: str
    verified: bool
    title: str = ""
    section: str | None = None
    page: int | None = None
    opportunity_id: int | None = None


@dataclass
class Answer:
    question: str
    answer: str
    refused: bool
    refusal_reason: str | None = None  # out_of_scope | no_passages | not_answerable | unverified
    citations: list[Citation] = field(default_factory=list)
    dropped_citations: list[Citation] = field(default_factory=list)
    passages: list[dict] = field(default_factory=list)
    top_score: float | None = None
    timings_ms: dict = field(default_factory=dict)
    model: str = MODEL
    scope: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        for p in d["passages"]:
            p["close_date"] = str(p["close_date"]) if p.get("close_date") else None
        return d


def format_passages(passages: list[dict]) -> str:
    blocks = []
    for i, p in enumerate(passages, start=1):
        header = f"[{i}] Grant: {p['title']}"
        if p.get("section"):
            header += f" | Section: {p['section']}"
        blocks.append(f"{header}\n{p['text']}")
    return "\n\n".join(blocks)


def verify(citation: dict, passages: list[dict]) -> Citation:
    try:
        idx = int(citation.get("passage", 0))
    except (TypeError, ValueError):
        idx = 0
    quote = str(citation.get("quote", "")).strip()
    if not 1 <= idx <= len(passages) or len(normalize(quote).split()) < 3:
        return Citation(passage=idx, quote=quote, verified=False)

    p = passages[idx - 1]
    # Same normalization as the eval set: ignores case, punctuation, bullets, ligatures.
    verified = normalize(quote) in normalize((p.get("section") or "") + " " + p["text"])
    page = p["page_start"]
    pdf = ROOT / "data" / "raw" / f"{p['opportunity_id']}.pdf"
    if verified and pdf.exists():
        page = find_quote_page(pdf, quote) or page  # exact page of the quote, not the chunk start
    return Citation(passage=idx, quote=quote, verified=verified, title=p["title"],
                    section=p.get("section"), page=page, opportunity_id=p["opportunity_id"])


def answer_question(
    conn: psycopg.Connection,
    question: str,
    filters: Filters | None = None,
    chunk_set: str = "section_300",
) -> Answer:
    timings = {}
    start = time.perf_counter()
    # Restrict the search to the agency/grant the question names, or refuse if it names only
    # agencies we have no grants from or a program our documents don't cover; see app/scope.py.
    scope = scope_question(conn, question)
    scope_info = {"agencies": scope.agencies, "agency_codes": scope.agency_codes,
                  "opportunity_ids": scope.opportunity_ids, "missing_program": scope.missing_program}
    if scope.refusal:
        timings["retrieval"] = round((time.perf_counter() - start) * 1000)
        return Answer(question, scope.refusal, True, "out_of_scope", timings_ms=timings, scope=scope_info)

    passages = search(conn, question, chunk_set, TOP_K, scoped_filters(filters, scope), method="hybrid_rerank")
    timings["retrieval"] = round((time.perf_counter() - start) * 1000)
    top_score = passages[0]["score"] if passages else None

    if not passages or top_score < MIN_RERANK_SCORE:
        return Answer(question, REFUSAL_NO_PASSAGES, True, "no_passages",
                      passages=passages, top_score=top_score, timings_ms=timings, scope=scope_info)

    start = time.perf_counter()
    raw = chat([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Question: {question}\n\nPassages:\n\n{format_passages(passages)}"},
    ])
    timings["generation"] = round((time.perf_counter() - start) * 1000)
    try:
        out = parse_json(raw)
    except ValueError:
        out = {"answerable": False}

    answer_text = str(out.get("answer", "")).strip()
    if not out.get("answerable") or not answer_text or is_non_answer(answer_text):
        return Answer(question, REFUSAL_NOT_ANSWERABLE, True, "not_answerable",
                      passages=passages, top_score=top_score, timings_ms=timings, scope=scope_info)

    checked = [verify(c, passages) for c in out.get("citations") or [] if isinstance(c, dict)]
    good = [c for c in checked if c.verified]
    bad = [c for c in checked if not c.verified]
    if not good:
        return Answer(question, REFUSAL_UNVERIFIED, True, "unverified", dropped_citations=bad,
                      passages=passages, top_score=top_score, timings_ms=timings, scope=scope_info)

    return Answer(question, answer_text, False, citations=good, dropped_citations=bad,
                  passages=passages, top_score=top_score, timings_ms=timings, scope=scope_info)
