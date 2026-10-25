# GrantScope

**Live demo: https://grantscope.mounikabharatha.workers.dev**

[![CI](https://github.com/Mounikabharatha/grantscope/actions/workflows/ci.yml/badge.svg)](https://github.com/Mounikabharatha/grantscope/actions/workflows/ci.yml)

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

Baseline (vector search, section-aware chunks): **recall@5 = 82.3%** on 79
answerable questions, vs 63.3% with fixed-size chunks. See
[docs/results.md](docs/results.md).

## Phase 5: hybrid search + reranker

```bash
python scripts/evaluate_retrieval.py   # compares vector, keyword, hybrid, vector_rerank, hybrid_rerank
python scripts/search.py "DERA question subject line" --method hybrid_rerank
```

- **Keyword search:** Postgres full-text over grant title (weight A), section heading (B) and text (C).
- **Hybrid:** vector + keyword merged with Reciprocal Rank Fusion (k=60).
- **Reranker:** `BAAI/bge-reranker-base` cross-encoder re-scores the top 30 (also hosted on Cloudflare Workers AI).

| Section-aware chunks, 79 questions | Recall@1 | Recall@5 | MRR | Right grant in top 5 | Median latency (Mac) |
|---|---|---|---|---|---|
| Vector (baseline) | 45.6% | 82.3% | 0.602 | 96.2% | 23 ms |
| Hybrid | 39.2% | 70.9% | 0.539 | 98.7% | 179 ms |
| Vector + reranker | 67.1% | 89.9% | 0.776 | 98.7% | 860 ms |
| **Hybrid + reranker (default)** | **64.6%** | **89.9%** | **0.765** | **100%** | 1,062 ms |

Most of the gain comes from the reranker; hybrid's contribution is exact-term
queries (acronyms, IDs) and always surfacing the right grant. Details in
[docs/results.md](docs/results.md).

## Phase 6: cited answers, quote verification, refusals

```bash
brew install ollama && brew services start ollama && ollama pull llama3.1:8b   # one time
python scripts/evaluate_answers.py        # all 93 questions, ~20 min on an M1 Pro
```

On the page, **Ask** returns an answer with the exact quotes it relies on (each checked word-for-word
against the source passage, with a link to the PDF page), or says it couldn't find a supported answer.
API: `GET /ask?q=...`

| 93 questions, Llama 3.1 8B local | Result |
|---|---|
| Unanswerable questions correctly refused | 92.9% (13/14) |
| Answerable questions answered | 93.7% (74/79) |
| Correct (of answered, reviewed) | 95.9% (71/74) |
| Faithful: every claim backed by a verified quote (reviewed) | 97.3% (73/75 answers shown) |
| Quotes found word-for-word in the cited passage | 96.1%; the rest were dropped before display |

Failures and how the numbers were checked: [docs/results.md](docs/results.md).

## Phase 7: continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push and pull request:

1. **Unit tests** and a check that every eval-set quote exists in the chunks.
2. **Retrieval quality gate:** starts a fresh Postgres + pgvector, rebuilds the search index from the
   committed chunk snapshot ([data/snapshot/](data/snapshot)), runs the 79-question retrieval eval on CPU,
   and **fails the build if recall@5 drops below 79% (vector) or 87% (hybrid + reranker)**. Results
   appear as a table on the run's summary page and as a downloadable artifact.

The answer-generation eval needs the 5 GB Llama model, so it runs locally
(`python scripts/evaluate_answers.py`). After re-chunking, refresh the snapshot with
`python scripts/make_snapshot.py`.

## Phase 8: live on Cloudflare

**Live: https://grantscope.mounikabharatha.workers.dev**

```
Browser ─► Cloudflare Worker (TypeScript, worker/)
             ├─ static assets: the search page + 200 grant PDFs
             ├─ Workers AI: bge-small-en-v1.5 (CLS), bge-reranker-base, Llama 3.1 8B (FP8)
             └─ Hyperdrive ─► Neon Postgres + pgvector (documents + 15,436 chunks, 98 MB)
```

The Worker is a port of the Python pipeline with the same SQL, prompt, RRF and quote-verification
rules (`worker/test` mirrors the Python unit tests). Before deploying, embeddings and reranker scores
from Workers AI were checked against the local models: identical (cosine 1.0000, same rankings).

| Live site, measured through its public API | Result |
|---|---|
| Retrieval recall@5 (hybrid + reranker, 79 questions) | **89.9%** (same as local) |
| Right grant in top 5 | 100% |
| Unanswerable questions refused | 78.6% (11/14) |
| Correct answers (of answered, reviewed) | 97.3% (71/73) |
| Faithful: claims backed by verified quotes (of all answers shown, reviewed) | 94.7% (72/76) |
| Median latency | search 1.8 s, answer 6.5 s |
| Cost | $0: Cloudflare and Neon free tiers |

Redeploy after changes:

```bash
python scripts/migrate_to_neon.py            # only if the data changed (needs NEON_DATABASE_URL in .env)
cd worker && npm run deploy                  # copies the page + PDFs into public/ and deploys
python scripts/evaluate_live.py --base-url https://grantscope.mounikabharatha.workers.dev
```

## Tests

```bash
python -m pytest            # Python
cd worker && npm test       # Worker (TypeScript) parity tests
```

## Run it locally

```bash
cd ~/Desktop/RAG/grantscope
source .venv/bin/activate
uvicorn app.main:app --port 8010
```

Wait for `Application startup complete` (the two AI models load first, ~10-20 s), then open:

| URL | What it is |
|---|---|
| http://localhost:8010 | Search page |
| http://localhost:8010/docs | Interactive API documentation |
| http://localhost:8010/health | Database check |

Stop the server with `Ctrl + C`.

## Progress

- [x] Phase 0: project setup
- [x] Phase 1: document collection script
- [x] Phase 2: section-aware chunking
- [x] Phase 3: embeddings + pgvector index
- [x] Phase 4: evaluation set + baseline score
- [x] Phase 5: hybrid search + reranker
- [x] Phase 6: cited answers, quote verification, refusals
- [x] Phase 7: evaluation in CI
- [x] Phase 8: deploy, cost and latency

Every measured number goes in [docs/results.md](docs/results.md).
