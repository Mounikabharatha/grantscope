"""Where chunk files live.

data/chunks/<set>.jsonl       full local output of scripts/chunk_documents.py (not in git)
data/snapshot/<set>.jsonl.gz  compressed copy committed to git, so CI can rebuild the
                              search index without the 110 MB of PDFs.
                              Refresh with scripts/make_snapshot.py after re-chunking.
"""

import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_DIR = ROOT / "data" / "chunks"
SNAPSHOT_DIR = ROOT / "data" / "snapshot"


def chunk_file(chunk_set: str) -> Path:
    local = CHUNKS_DIR / f"{chunk_set}.jsonl"
    if local.exists():
        return local
    snapshot = SNAPSHOT_DIR / f"{chunk_set}.jsonl.gz"
    if snapshot.exists():
        return snapshot
    raise FileNotFoundError(f"No chunks for {chunk_set!r}: run scripts/chunk_documents.py first")


def read_chunks(chunk_set: str) -> list[dict]:
    path = chunk_file(chunk_set)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
