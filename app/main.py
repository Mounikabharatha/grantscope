"""GrantScope API."""

import os
from datetime import date
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, Query

from app.search import METHODS, Filters, search as run_search

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = FastAPI(title="GrantScope")


@app.get("/health")
def health() -> dict:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        pgvector = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
        docs = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
    return {
        "status": "ok",
        "pgvector_version": pgvector[0] if pgvector else None,
        "documents": docs,
    }


@app.get("/search")
def search(
    q: str = Query(..., min_length=3, description="your question"),
    k: int = Query(5, ge=1, le=20),
    agency: str | None = None,
    min_award: int | None = None,
    open_on: date | None = None,
    chunk_set: str = "section_300",
    method: str = Query("hybrid_rerank", enum=METHODS),
) -> dict:
    filters = Filters(agency_code=agency, min_award=min_award, open_on=open_on)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        hits = run_search(conn, q, chunk_set, k, filters, method)
    return {"query": q, "method": method, "results": hits}
