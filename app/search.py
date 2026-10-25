"""Retrieval: vector, keyword, hybrid, and reranked search with metadata filters.

vector   - meaning-based. `<=>` is pgvector's cosine distance (0 = same
           direction, 2 = opposite), so similarity = 1 - distance. The HNSW
           index walks a graph of neighbours instead of comparing every chunk.
keyword  - Postgres full-text search. Exact words win: acronyms ("DERA"),
           names, numbers. Grant-title matches weigh most, then section, then text.
hybrid   - run both and merge with Reciprocal Rank Fusion (RRF): each chunk
           scores sum(1 / (60 + rank)) over the lists it appears in. RRF only
           uses ranks, so the two very different score scales never need tuning.
scoped   - hybrid_rerank restricted to the agency/grant the question names (app/scope.py)
*_rerank - a cross-encoder (BAAI/bge-reranker-base) reads the question and each
           candidate together and re-orders the top candidates. Slower but much
           more precise than comparing two separately computed vectors.

Settings are standard defaults chosen before evaluation (RRF k=60, 50
candidates per list, rerank top 30), not tuned on the evaluation set.
"""

from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import psycopg

from app.embeddings import embed_query

RRF_K = 60
CANDIDATES = 50
RERANK_CANDIDATES = 30
RERANKER_MODEL = "BAAI/bge-reranker-base"  # also on Cloudflare Workers AI
METHODS = ["vector", "keyword", "hybrid", "vector_rerank", "hybrid_rerank", "scoped"]

COLUMNS = """c.chunk_id, c.opportunity_id, c.section, c.page_start, c.page_end, c.text,
             d.title, d.agency_code, d.award_ceiling, d.close_date, d.source_url"""


@dataclass
class Filters:
    agency_code: str | None = None
    min_award: int | None = None  # award ceiling at least this much
    open_on: date | None = None   # deadline on or after this date
    agency_codes: list[str] | None = None     # set by app.scope from the question
    opportunity_ids: list[int] | None = None  # set by app.scope from the question


def filter_sql(filters: Filters) -> tuple[str, dict]:
    clauses, params = [], {}
    if filters.agency_code:
        clauses.append("d.agency_code = %(agency_code)s")
        params["agency_code"] = filters.agency_code
    if filters.min_award is not None:
        clauses.append("d.award_ceiling >= %(min_award)s")
        params["min_award"] = filters.min_award
    if filters.open_on:
        clauses.append("d.close_date >= %(open_on)s")
        params["open_on"] = filters.open_on
    if filters.agency_codes:
        clauses.append("d.agency_code = ANY(%(agency_codes)s)")
        params["agency_codes"] = filters.agency_codes
    if filters.opportunity_ids:
        clauses.append("d.opportunity_id = ANY(%(opportunity_ids)s)")
        params["opportunity_ids"] = filters.opportunity_ids
    return "".join(f" AND {c}" for c in clauses), params


def vector_search(
    conn: psycopg.Connection,
    query: str,
    chunk_set: str = "section_300",
    k: int = 5,
    filters: Filters | None = None,
) -> list[dict]:
    where, params = filter_sql(filters or Filters())
    params |= {
        "query_vec": "[" + ",".join(map(str, embed_query(query))) + "]",
        "chunk_set": chunk_set,
        "k": k,
    }
    sql = f"""
        SELECT {COLUMNS}, 1 - (c.embedding <=> %(query_vec)s::vector) AS score
        FROM chunks c JOIN documents d USING (opportunity_id)
        WHERE c.chunk_set = %(chunk_set)s {where}
        ORDER BY c.embedding <=> %(query_vec)s::vector
        LIMIT %(k)s
    """
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        # With filters, HNSW may find too few matches; iterative scans
        # (pgvector >= 0.8) keep searching until LIMIT is satisfied.
        cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        cur.execute(sql, params)
        return cur.fetchall()


def keyword_search(
    conn: psycopg.Connection,
    query: str,
    chunk_set: str = "section_300",
    k: int = 5,
    filters: Filters | None = None,
) -> list[dict]:
    """Full-text search where any query word may match (OR), ranked by how many
    match, how close together they are, and where (title > section > text).

    websearch_to_tsquery would AND every word, so a natural question like
    "Can tribes apply?" would almost never match; OR + ranking fixes that.
    Stop words ("what", "is", "the") are dropped by to_tsvector.
    """
    where, params = filter_sql(filters or Filters())
    params |= {"query": query, "chunk_set": chunk_set, "k": k}
    sql = f"""
        WITH terms AS (
            SELECT string_agg(quote_literal(lexeme), ' | ') AS q
            FROM unnest(tsvector_to_array(to_tsvector('english', %(query)s))) AS lexeme
        ), tsq AS (
            SELECT to_tsquery('english', q) AS q FROM terms WHERE q IS NOT NULL
        )
        SELECT {COLUMNS}, ts_rank_cd(c.tsv, tsq.q, 1) AS score
        FROM chunks c JOIN documents d USING (opportunity_id), tsq
        WHERE c.chunk_set = %(chunk_set)s AND c.tsv @@ tsq.q {where}
        ORDER BY score DESC
        LIMIT %(k)s
    """
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def rrf_fuse(result_lists: list[list[dict]], k: int) -> list[dict]:
    scores: dict[str, float] = {}
    rows: dict[str, dict] = {}
    for results in result_lists:
        for rank, row in enumerate(results, start=1):
            scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + 1 / (RRF_K + rank)
            rows.setdefault(row["chunk_id"], row)
    best = sorted(scores, key=scores.get, reverse=True)[:k]
    return [{**rows[cid], "score": scores[cid]} for cid in best]


def hybrid_search(conn, query, chunk_set="section_300", k=5, filters=None) -> list[dict]:
    return rrf_fuse([
        vector_search(conn, query, chunk_set, CANDIDATES, filters),
        keyword_search(conn, query, chunk_set, CANDIDATES, filters),
    ], k)


@lru_cache(maxsize=1)
def get_reranker():
    import torch
    from sentence_transformers import CrossEncoder

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    return CrossEncoder(RERANKER_MODEL, device=device, max_length=512)


def rerank(query: str, candidates: list[dict], k: int) -> list[dict]:
    if not candidates:
        return []
    # Give the reranker the same context the embedding saw: which grant and section.
    passages = [f"{c['title']}\n{c['section'] or ''}\n\n{c['text']}" for c in candidates]
    scores = get_reranker().predict([(query, p) for p in passages], batch_size=16)
    ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)[:k]
    return [{**c, "score": float(s)} for c, s in ranked]


def search(
    conn: psycopg.Connection,
    query: str,
    chunk_set: str = "section_300",
    k: int = 5,
    filters: Filters | None = None,
    method: str = "hybrid_rerank",
) -> list[dict]:
    if method == "vector":
        return vector_search(conn, query, chunk_set, k, filters)
    if method == "keyword":
        return keyword_search(conn, query, chunk_set, k, filters)
    if method == "hybrid":
        return hybrid_search(conn, query, chunk_set, k, filters)
    if method == "vector_rerank":
        candidates = vector_search(conn, query, chunk_set, max(k, RERANK_CANDIDATES), filters)
        return rerank(query, candidates, k)
    if method == "hybrid_rerank":
        candidates = hybrid_search(conn, query, chunk_set, max(k, RERANK_CANDIDATES), filters)
        return rerank(query, candidates, k)
    if method == "scoped":
        from app.scope import scope_question, scoped_filters

        scope = scope_question(conn, query)
        if scope.refusal:
            return []
        return search(conn, query, chunk_set, k, scoped_filters(filters, scope), "hybrid_rerank")
    raise ValueError(f"unknown method {method!r}; choose from {METHODS}")
