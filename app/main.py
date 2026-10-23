"""GrantScope API. Phase 0: just proves the app can reach Postgres + pgvector."""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI

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
