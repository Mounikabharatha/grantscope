"""GrantScope API and search page.

  /          search page (app/static/index.html)
  /ask       answer with verified citations, or a refusal (JSON)
  /search    JSON search API
  /agencies  agencies and grant counts, for the page's filter
  /pdfs/...  the downloaded grant PDFs, so results can link to the exact page
  /health    database + pgvector check
  /docs      interactive API documentation (built into FastAPI)
"""

import os
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.answer import answer_question
from app.embeddings import get_model
from app.search import METHODS, Filters, get_reranker, search as run_search

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load both models at startup so the first search isn't slow.
    get_model()
    get_reranker()
    yield


app = FastAPI(title="GrantScope", lifespan=lifespan)
app.mount("/pdfs", StaticFiles(directory=ROOT / "data" / "raw"), name="pdfs")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


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


@app.get("/agencies")
def agencies() -> list[dict]:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(
            "SELECT agency_code, min(agency), count(*) FROM documents GROUP BY 1 ORDER BY 3 DESC"
        ).fetchall()
    return [{"code": code, "name": name, "grants": n} for code, name, n in rows]


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
    start = time.perf_counter()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        hits = run_search(conn, q, chunk_set, k, filters, method)
    return {
        "query": q,
        "method": method,
        "took_ms": round((time.perf_counter() - start) * 1000),
        "results": hits,
    }


@app.get("/ask")
def ask(
    q: str = Query(..., min_length=3, description="your question"),
    agency: str | None = None,
    min_award: int | None = None,
    open_on: date | None = None,
) -> dict:
    filters = Filters(agency_code=agency, min_award=min_award, open_on=open_on)
    start = time.perf_counter()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        result = answer_question(conn, q, filters)
    return {**result.to_dict(), "took_ms": round((time.perf_counter() - start) * 1000)}
