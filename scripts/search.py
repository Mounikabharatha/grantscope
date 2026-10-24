"""Try a search from the terminal.

Usage:
  python scripts/search.py "Can tribal governments apply for wildlife grants?"
  python scripts/search.py "cost sharing" --agency EPA --k 3
  python scripts/search.py "DERA deadline" --method keyword
"""

import argparse
import os
import sys
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.embeddings import get_model  # noqa: E402
from app.search import METHODS, Filters, search  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--chunk-set", default="section_300")
    parser.add_argument("--agency")
    parser.add_argument("--min-award", type=int)
    parser.add_argument("--method", default="hybrid_rerank", choices=METHODS)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    get_model()  # load once so the timing below is just the search
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        start = time.perf_counter()
        hits = search(conn, args.query, args.chunk_set, args.k,
                      Filters(agency_code=args.agency, min_award=args.min_award), args.method)
        ms = (time.perf_counter() - start) * 1000

    for i, h in enumerate(hits, 1):
        print(f"\n{i}. [{h['score']:.3f}] {h['title'][:80]}  ({h['agency_code']}, p.{h['page_start']})")
        print(f"   Section: {h['section'] or '-'}")
        print(f"   {h['text'][:300]}")
    print(f"\nSearch ({args.method}) took {ms:.0f} ms.")


if __name__ == "__main__":
    main()
