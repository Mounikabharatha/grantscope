"""Phase 1: download public grant announcement PDFs from Grants.gov.

Uses the free, no-key Grants.gov REST API:
  - search2          -> list of opportunities
  - fetchOpportunity -> details (award amounts, deadline, attachments)
  - att/download     -> the attachment file itself

For each opportunity we keep the main "Full Announcement" PDF (the NOFO) and
write one line of metadata to data/metadata.jsonl. Safe to re-run: grants
already in metadata.jsonl are skipped.

Usage:
  python scripts/fetch_grants.py --limit 10
  python scripts/fetch_grants.py --limit 300 --agencies "EPA|NEH" --status posted
"""

import argparse
import hashlib
import html
import json
import re
import time
from pathlib import Path

import requests

API = "https://api.grants.gov/v1/api"
DOWNLOAD = "https://apply07.grants.gov/grantsws/rest/opportunity/att/download/{}"
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
METADATA = ROOT / "data" / "metadata.jsonl"

# A PDF whose name looks like the main announcement wins over forms/templates.
NOFO_HINTS = re.compile(r"nofo|nofa|foa|announcement|solicitation|rfa|funding opportunity", re.I)
MAX_PDF_BYTES = 25_000_000
PAUSE_SECONDS = 0.5  # be polite to a public government API

# Agencies that reliably attach their announcement as a PDF (NIH and NSF
# mostly don't). Codes must match Grants.gov exactly; sub-agencies aren't
# included automatically.
DEFAULT_AGENCIES = "EPA|USDA-NIFA|NEH|HHS-HRSA|DOS-DRL|DOI-FWS"

session = requests.Session()
session.headers["User-Agent"] = "GrantScope research project (educational)"


def post(endpoint: str, body: dict) -> dict:
    resp = session.post(f"{API}/{endpoint}", json=body, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errorcode") != 0:
        raise RuntimeError(f"{endpoint} failed: {payload.get('msg')}")
    return payload["data"]


def search(agencies: str, status: str, start: int, rows: int) -> list[dict]:
    body = {
        "agencies": agencies,
        "oppStatuses": status,
        "startRecordNum": start,
        "rows": rows,
        "sortBy": "openDate|desc",
    }
    data = post("search2", body)
    return data["oppHits"]


def pick_nofo_pdf(details: dict) -> dict | None:
    """Return the attachment most likely to be the main announcement PDF."""
    candidates = []
    for folder in details.get("synopsisAttachmentFolders") or []:
        is_full = folder.get("folderType") == "Full Announcement"
        for att in folder.get("synopsisAttachments") or []:
            name = att.get("fileName", "")
            size = att.get("fileLobSize") or 0
            if not name.lower().endswith(".pdf") or not 0 < size <= MAX_PDF_BYTES:
                continue
            text = f"{name} {att.get('fileDescription', '')}"
            # Rank: Full Announcement folder, then NOFO-like name, then size.
            candidates.append(((is_full, bool(NOFO_HINTS.search(text)), size), att))
    if not candidates:
        return None
    return max(candidates, key=lambda c: c[0])[1]


def to_number(value) -> int | None:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def build_record(hit: dict, details: dict, att: dict, pdf_path: Path, sha256: str) -> dict:
    syn = details.get("synopsis") or {}
    return {
        "opportunity_id": int(hit["id"]),
        "opportunity_number": hit.get("number"),
        "title": html.unescape(hit.get("title") or ""),
        "agency_code": hit.get("agencyCode"),
        "agency": html.unescape(hit.get("agency") or ""),
        "status": hit.get("oppStatus"),
        "open_date": hit.get("openDate") or None,
        "close_date": hit.get("closeDate") or None,
        "award_ceiling": to_number(syn.get("awardCeiling")),
        "award_floor": to_number(syn.get("awardFloor")),
        "estimated_total_funding": to_number(syn.get("estimatedFunding")),
        "categories": [c.get("description") for c in syn.get("fundingActivityCategories") or []],
        "applicant_types": [a.get("description") for a in syn.get("applicantTypes") or []],
        "cfda_numbers": hit.get("cfdaList") or [],
        "source_url": f"https://www.grants.gov/search-results-detail/{hit['id']}",
        "pdf_url": DOWNLOAD.format(att["id"]),
        "pdf_file": pdf_path.name,
        "pdf_sha256": sha256,
        "pdf_bytes": pdf_path.stat().st_size,
    }


def load_done() -> set[int]:
    if not METADATA.exists():
        return set()
    with METADATA.open() as f:
        return {json.loads(line)["opportunity_id"] for line in f if line.strip()}


def download(att_id: int, dest: Path) -> str:
    resp = session.get(DOWNLOAD.format(att_id), timeout=120)
    resp.raise_for_status()
    if not resp.content.startswith(b"%PDF"):
        raise ValueError("response is not a PDF")
    dest.write_bytes(resp.content)
    return hashlib.sha256(resp.content).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=10, help="how many new PDFs to download")
    parser.add_argument("--agencies", default=DEFAULT_AGENCIES, help="pipe-separated Grants.gov agency codes")
    parser.add_argument(
        "--status",
        default="posted|closed|archived",
        help="pipe-separated: posted, closed, archived, forecasted",
    )
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    done = load_done()
    seen_hashes = set()
    saved = skipped = start = 0
    page_size = 50

    print(f"Already have {len(done)} grants. Downloading up to {args.limit} more...")
    while saved < args.limit:
        hits = search(args.agencies, args.status, start, page_size)
        if not hits:
            print("No more search results.")
            break
        start += page_size

        for hit in hits:
            if saved >= args.limit:
                break
            opp_id = int(hit["id"])
            if opp_id in done:
                continue
            try:
                details = post("fetchOpportunity", {"opportunityId": opp_id})
                att = pick_nofo_pdf(details)
                if att is None:
                    skipped += 1
                    continue
                pdf_path = RAW_DIR / f"{opp_id}.pdf"
                sha256 = download(att["id"], pdf_path)
                if sha256 in seen_hashes:  # same PDF reused by another listing
                    pdf_path.unlink()
                    skipped += 1
                    continue
                seen_hashes.add(sha256)
                record = build_record(hit, details, att, pdf_path, sha256)
            except Exception as exc:  # one bad grant shouldn't stop the run
                print(f"  ! {opp_id}: {exc}")
                skipped += 1
                continue
            finally:
                time.sleep(PAUSE_SECONDS)

            with METADATA.open("a") as f:
                f.write(json.dumps(record) + "\n")
            done.add(opp_id)
            saved += 1
            print(f"  [{saved}/{args.limit}] {record['agency_code']:<12} {record['title'][:70]}", flush=True)

    print(f"Done. Saved {saved} new PDFs, skipped {skipped} (no PDF / duplicate / error).")
    print(f"PDFs: {RAW_DIR}\nMetadata: {METADATA}")


if __name__ == "__main__":
    main()
