"""Phase 8: copy the search database to Neon (hosted Postgres) for the Cloudflare deployment.

Copies the `documents` table and the section_300 chunks (with their embeddings and keyword
index) from the local database to Neon, then builds the indexes there. fixed_300 stays local:
it was only for the chunking experiment.

Setup: add this line to .env (never commit it; .env is git-ignored):
  NEON_DATABASE_URL=postgresql://...   (Neon console > Connect > connection string)

Usage:
  python scripts/migrate_to_neon.py
"""

import os
import sys
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CHUNK_SET = "section_300"

TABLES_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
DROP TABLE IF EXISTS chunks;
DROP TABLE IF EXISTS documents;
"""

INDEXES_SQL = [
    "CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv)",
    "CREATE INDEX chunks_opportunity ON chunks (opportunity_id)",
    "ANALYZE documents",
    "ANALYZE chunks",
]

CHUNK_COLUMNS = ("chunk_set, chunk_id, opportunity_id, chunk_index, section, page_start, page_end, "
                 "text, n_words, embedding, tsv")


def table_ddl(path: Path) -> str:
    """CREATE TABLE statements from db/schema.sql, without the indexes (built after loading)."""
    statements = [s.strip() for s in path.read_text().split(";")]
    keep = [s for s in statements if "CREATE TABLE" in s]
    return ";\n".join(keep) + ";"


def copy_table(src, dst, select_sql: str, target: str) -> int:
    rows = 0
    with src.cursor().copy(f"COPY ({select_sql}) TO STDOUT (FORMAT BINARY)") as out, \
            dst.cursor().copy(f"COPY {target} FROM STDIN (FORMAT BINARY)") as into:
        for block in out:
            into.write(block)
            rows += 1
    return rows


def main() -> None:
    load_dotenv(ROOT / ".env")
    neon_url = os.environ.get("NEON_DATABASE_URL")
    if not neon_url or "neon.tech" not in neon_url:
        sys.exit("NEON_DATABASE_URL is missing from .env (see this script's docstring).")

    with psycopg.connect(os.environ["DATABASE_URL"]) as local, psycopg.connect(neon_url) as neon:
        print("Creating tables on Neon...")
        neon.execute(TABLES_SQL)
        neon.execute(table_ddl(ROOT / "db" / "schema.sql"))

        print("Copying documents...")
        copy_table(local, neon, "SELECT * FROM documents", "documents")
        print(f"Copying {CHUNK_SET} chunks with embeddings and keyword index...")
        copy_table(local, neon, f"SELECT {CHUNK_COLUMNS} FROM chunks WHERE chunk_set = '{CHUNK_SET}'",
                   f"chunks ({CHUNK_COLUMNS})")
        neon.commit()

        print("Building indexes on Neon (the HNSW index takes a few minutes)...")
        neon.execute("SET maintenance_work_mem = '256MB'")
        for stmt in INDEXES_SQL:
            start = time.perf_counter()
            neon.execute(stmt)
            print(f"  {stmt.split(' ON ')[0][:45]:<45} {time.perf_counter() - start:6.1f}s")
        neon.commit()

        n_docs = neon.execute("SELECT count(*) FROM documents").fetchone()[0]
        n_chunks = neon.execute("SELECT count(*) FROM chunks").fetchone()[0]
        size = neon.execute("SELECT pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
        local_chunks = local.execute("SELECT count(*) FROM chunks WHERE chunk_set = %s", (CHUNK_SET,)).fetchone()[0]

    print(f"\nNeon now has {n_docs} documents and {n_chunks} chunks (local: {local_chunks}); database size {size}.")
    if n_chunks != local_chunks:
        sys.exit("Chunk counts differ: something went wrong.")


if __name__ == "__main__":
    main()
