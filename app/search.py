"""Phase 3: vector search with metadata filters.

`<=>` is pgvector's cosine distance (0 = same direction, 2 = opposite), so
similarity = 1 - distance. The HNSW index makes this an approximate search:
it walks a graph of neighbours instead of comparing against every chunk.
"""

from dataclasses import dataclass
from datetime import date

import psycopg

from app.embeddings import embed_query


@dataclass
class Filters:
    agency_code: str | None = None
    min_award: int | None = None  # award ceiling at least this much
    open_on: date | None = None   # deadline on or after this date


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
        SELECT c.chunk_id, c.opportunity_id, c.section, c.page_start, c.page_end, c.text,
               d.title, d.agency_code, d.award_ceiling, d.close_date, d.source_url,
               1 - (c.embedding <=> %(query_vec)s::vector) AS score
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
