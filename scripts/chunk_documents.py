"""Phase 2: chunk every downloaded PDF and save the chunks to a JSONL file.

Usage:
  python scripts/chunk_documents.py                          # section-aware, 300 words
  python scripts/chunk_documents.py --strategy fixed         # baseline for comparison
  python scripts/chunk_documents.py --chunk-words 150 --overlap-words 30

Output: data/chunks/<strategy>_<chunk-words>.jsonl, one chunk per line.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.chunking import chunk_pdf  # noqa: E402

RAW_DIR = ROOT / "data" / "raw"
METADATA = ROOT / "data" / "metadata.jsonl"
OUT_DIR = ROOT / "data" / "chunks"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strategy", choices=["section", "fixed"], default="section")
    parser.add_argument("--chunk-words", type=int, default=300)
    parser.add_argument("--overlap-words", type=int, default=50)
    args = parser.parse_args()

    docs = [json.loads(line) for line in METADATA.open() if line.strip()]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{args.strategy}_{args.chunk_words}.jsonl"

    sizes, no_text, no_sections = [], [], 0
    with out_path.open("w") as out:
        for doc in docs:
            pdf = RAW_DIR / doc["pdf_file"]
            if not pdf.exists():
                continue
            chunks = chunk_pdf(pdf, args.strategy, args.chunk_words, args.overlap_words)
            if not chunks:
                no_text.append(doc["pdf_file"])  # probably a scanned image PDF
                continue
            if args.strategy == "section" and all(c["section"] is None for c in chunks):
                no_sections += 1
            for chunk in chunks:
                chunk["chunk_id"] = f"{doc['opportunity_id']}-{chunk['chunk_index']:04d}"
                chunk["opportunity_id"] = doc["opportunity_id"]
                chunk["strategy"] = args.strategy
                out.write(json.dumps(chunk) + "\n")
                sizes.append(chunk["n_words"])

    print(f"Wrote {len(sizes)} chunks from {len(docs) - len(no_text)} PDFs -> {out_path}")
    if sizes:
        print(f"Words per chunk: median {statistics.median(sizes):.0f}, "
              f"mean {statistics.mean(sizes):.0f}, max {max(sizes)}")
    if args.strategy == "section":
        print(f"PDFs where no headings were found: {no_sections}")
    if no_text:
        print(f"PDFs with no extractable text (need OCR): {len(no_text)} {no_text[:5]}")


if __name__ == "__main__":
    main()
