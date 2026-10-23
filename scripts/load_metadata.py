"""Phase 1: load data/metadata.jsonl into the Postgres `documents` table.

Safe to re-run: existing rows are updated in place.

Usage:
  python scripts/load_metadata.py
"""

import json
import os
from datetime import datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
METADATA = ROOT / "data" / "metadata.jsonl"
COLUMNS = [
    "opportunity_id", "opportunity_number", "title", "agency_code", "agency", "status",
    "open_date", "close_date", "award_ceiling", "award_floor", "estimated_total_funding",
    "categories", "applicant_types", "cfda_numbers", "source_url", "pdf_url",
    "pdf_file", "pdf_sha256", "pdf_bytes",
]


def parse_date(value: str | None):
    return datetime.strptime(value, "%m/%d/%Y").date() if value else None


def main() -> None:
    load_dotenv(ROOT / ".env")
    rows = [json.loads(line) for line in METADATA.open() if line.strip()]
    for row in rows:
        row["open_date"] = parse_date(row["open_date"])
        row["close_date"] = parse_date(row["close_date"])

    placeholders = ", ".join(f"%({c})s" for c in COLUMNS)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS[1:])
    sql = (
        f"INSERT INTO documents ({', '.join(COLUMNS)}) VALUES ({placeholders}) "
        f"ON CONFLICT (opportunity_id) DO UPDATE SET {updates}"
    )
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.cursor().executemany(sql, rows)
        count = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
    print(f"Loaded {len(rows)} rows. documents table now has {count} grants.")


if __name__ == "__main__":
    main()
