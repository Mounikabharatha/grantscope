"""Phase 3: embed a chunk file and load it into the Postgres `chunks` table.

Usage:
  python scripts/embed_chunks.py                       # data/chunks/section_300.jsonl
  python scripts/embed_chunks.py --chunk-set fixed_300

Re-running replaces that chunk set.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.data import read_chunks  # noqa: E402
from app.embeddings import MODEL_NAME, embed_passages, passage_text  # noqa: E402

# Keyword index: title matches count most (A), then section heading (B), then text (C).
TSV_SQL = """
    UPDATE chunks c
    SET tsv = setweight(to_tsvector('english', d.title), 'A')
           || setweight(to_tsvector('english', coalesce(c.section, '')), 'B')
           || setweight(to_tsvector('english', c.text), 'C')
    FROM documents d
    WHERE d.opportunity_id = c.opportunity_id AND c.chunk_set = %s
"""

COLUMNS = ["chunk_set", "chunk_id", "opportunity_id", "chunk_index", "section",
           "page_start", "page_end", "text", "n_words", "embedding"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chunk-set", default="section_300")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    docs = {d["opportunity_id"]: d for d in map(json.loads, (ROOT / "data" / "metadata.jsonl").open())}
    chunks = read_chunks(args.chunk_set)  # local .jsonl, or the committed snapshot in CI

    print(f"Embedding {len(chunks)} chunks with {MODEL_NAME}...")
    start = time.perf_counter()
    vectors = embed_passages([passage_text(c, docs[c["opportunity_id"]]) for c in chunks])
    seconds = time.perf_counter() - start
    print(f"Embedded in {seconds:.0f}s ({len(chunks) / seconds:.0f} chunks/s), {vectors.shape[1]} dimensions")

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("DELETE FROM chunks WHERE chunk_set = %s", (args.chunk_set,))
        with conn.cursor().copy(f"COPY chunks ({', '.join(COLUMNS)}) FROM STDIN") as copy:
            for chunk, vector in zip(chunks, vectors):
                copy.write_row([
                    args.chunk_set, chunk["chunk_id"], chunk["opportunity_id"], chunk["chunk_index"],
                    chunk["section"], chunk["page_start"], chunk["page_end"], chunk["text"],
                    chunk["n_words"], "[" + ",".join(f"{x:.6f}" for x in vector) + "]",
                ])
        conn.execute(TSV_SQL, (args.chunk_set,))
        conn.execute("ANALYZE chunks")
        count = conn.execute("SELECT count(*) FROM chunks WHERE chunk_set = %s", (args.chunk_set,)).fetchone()[0]
    print(f"Loaded {count} rows into chunks (chunk_set={args.chunk_set}).")


if __name__ == "__main__":
    main()
