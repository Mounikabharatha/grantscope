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

## Phase 2: split PDFs into chunks

```bash
python scripts/chunk_documents.py                    # section-aware (default)
python scripts/chunk_documents.py --strategy fixed   # baseline, for comparison
```

Section-aware chunking finds headings by font size and boldness, keeps the
heading path with each chunk (e.g. `ELIGIBILITY > Eligible Applicants`) and
never lets a chunk cross a section boundary. Chunks also record their page
numbers for citations.

## Phase 3: embeddings + vector search

```bash
python scripts/embed_chunks.py                         # section_300 chunks
python scripts/embed_chunks.py --chunk-set fixed_300   # baseline chunks
python scripts/search.py "Can tribal governments apply for wildlife grants?"
```

Embeddings come from `BAAI/bge-small-en-v1.5` (384 dimensions), a free model
that runs locally. Cloudflare Workers AI hosts the same model, so the
deployed app can embed queries identically. Each chunk is embedded together
with its grant title, agency and section heading, while the stored text stays
unchanged for quoting. Vectors live in Postgres (pgvector) with an HNSW index
for cosine distance.

API: `GET /search?q=...&k=5&agency=EPA&min_award=500000&open_on=2026-11-01`

## Phase 4: evaluation set

[eval/questions.csv](eval/questions.csv): questions written from the PDFs, each
with the grant, page and an exact evidence quote, plus unanswerable questions
for testing refusals. See [eval/README.md](eval/README.md) for how to review.

```bash
python scripts/check_eval_set.py      # every evidence quote must exist in the PDFs
python scripts/review_eval.py --sample 20   # human spot-check
python scripts/evaluate_retrieval.py  # recall@k, MRR for each chunk set
```

Baseline (vector search, section-aware chunks): **recall@5 = 82.1%** on 78
answerable questions, vs 64.1% with fixed-size chunks. See
[docs/results.md](docs/results.md).

## Phase 5: hybrid search + reranker

```bash
python scripts/evaluate_retrieval.py   # compares vector, keyword, hybrid, vector_rerank, hybrid_rerank
python scripts/search.py "DERA question subject line" --method hybrid_rerank
```

- **Keyword search:** Postgres full-text over grant title (weight A), section heading (B) and text (C).
- **Hybrid:** vector + keyword merged with Reciprocal Rank Fusion (k=60).
- **Reranker:** `BAAI/bge-reranker-base` cross-encoder re-scores the top 30 (also hosted on Cloudflare Workers AI).

| Section-aware chunks, 78 questions | Recall@1 | Recall@5 | MRR | Right grant in top 5 | Median latency (Mac) |
|---|---|---|---|---|---|
| Vector (baseline) | 46.2% | 82.1% | 0.607 | 96.2% | 21 ms |
| Hybrid | 38.5% | 70.5% | 0.533 | 98.7% | 186 ms |
| Vector + reranker | 67.9% | 89.7% | 0.783 | 98.7% | 840 ms |
| **Hybrid + reranker (default)** | **65.4%** | **89.7%** | **0.771** | **100%** | 1,082 ms |

Most of the gain comes from the reranker; hybrid's contribution is exact-term
queries (acronyms, IDs) and always surfacing the right grant. Details in
[docs/results.md](docs/results.md).

## Tests

```bash
python -m pytest
```

## Run the API

```bash
uvicorn app.main:app --reload
# open http://127.0.0.1:8000/health
```

## Progress

- [x] Phase 0: project setup
- [x] Phase 1: document collection script
- [x] Phase 2: section-aware chunking
- [x] Phase 3: embeddings + pgvector index
- [x] Phase 4: evaluation set + baseline score
- [x] Phase 5: hybrid search + reranker
- [ ] Phase 6: cited answers, quote verification, refusals
- [ ] Phase 7: evaluation in CI
- [ ] Phase 8: deploy, cost and latency

Every measured number goes in [docs/results.md](docs/results.md).
