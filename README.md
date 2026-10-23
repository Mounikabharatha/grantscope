# GrantScope

Ask questions about public grant documents and get answers with citations.
The answers come only from the documents, and the system says "I don't know"
when the documents don't contain the answer.

**Data source:** grant announcement PDFs (NOFOs) from the free public
[Grants.gov API](https://www.grants.gov/api), currently from EPA, USDA-NIFA,
NEH, HHS-HRSA, DOS-DRL and DOI-FWS.

## Setup (one time)

```bash
# 1. Database: Postgres + pgvector
brew install postgresql@17 pgvector
brew services start postgresql@17
/opt/homebrew/opt/postgresql@17/bin/createdb grantscope
/opt/homebrew/opt/postgresql@17/bin/psql grantscope -f db/schema.sql

# 2. Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Phase 1: collect documents

```bash
python scripts/fetch_grants.py --limit 200   # downloads PDFs into data/raw/
python scripts/load_metadata.py              # loads metadata.jsonl into Postgres
```

## Run the API

```bash
uvicorn app.main:app --reload
# open http://127.0.0.1:8000/health
```

## Progress

- [x] Phase 0: project setup
- [x] Phase 1: document collection script
- [ ] Phase 2: section-aware chunking
- [ ] Phase 3: embeddings + pgvector index
- [ ] Phase 4: evaluation set + baseline score
- [ ] Phase 5: hybrid search + reranker
- [ ] Phase 6: cited answers, quote verification, refusals
- [ ] Phase 7: evaluation in CI
- [ ] Phase 8: deploy, cost and latency

Every measured number goes in [docs/results.md](docs/results.md).
