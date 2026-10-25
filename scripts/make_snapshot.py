"""Phase 7: write compressed chunk snapshots for CI.

CI can't download the 110 MB of PDFs on every run, so it rebuilds the search
index from these committed snapshots instead. Run this after re-chunking.

Usage:
  python scripts/make_snapshot.py                 # section_300
  python scripts/make_snapshot.py section_300 fixed_300
"""

import gzip
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.data import CHUNKS_DIR, SNAPSHOT_DIR  # noqa: E402


def main() -> None:
    chunk_sets = sys.argv[1:] or ["section_300"]
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for chunk_set in chunk_sets:
        src = CHUNKS_DIR / f"{chunk_set}.jsonl"
        dst = SNAPSHOT_DIR / f"{chunk_set}.jsonl.gz"
        # mtime=0 makes the file byte-identical when the content is unchanged, so git sees no diff.
        with src.open("rb") as f_in, open(dst, "wb") as raw, \
                gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as f_out:
            f_out.write(f_in.read())
        print(f"{src.relative_to(ROOT)} -> {dst.relative_to(ROOT)} ({dst.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
