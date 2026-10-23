# Experiment log

Rule: only numbers that were actually measured go here, and only numbers
from here go on the resume.

## Dataset

| Date | # PDFs | Agencies | Notes |
|---|---|---|---|
| 2026-10-23 | 200 (110 MB) | HHS-HRSA 56, USDA-NIFA 48, DOS-DRL 28, DOI-FWS 28, EPA 28, NEH 12 | Grants.gov posted/closed/archived, newest first. 0 download errors. |

## Chunking

| Date | Strategy | Chunk words / overlap | # chunks | Median words | Notes |
|---|---|---|---|---|---|
| 2026-10-23 | section | 300 / 50 | 15,436 | 89 | Headings found in all 200 PDFs. 1,253 chunks under 10 words (e.g. "Cost Sharing Required? No"). Try merging tiny sections in Phase 5. |
| 2026-10-23 | fixed | 300 / 50 | 7,406 | 291 | Baseline. |

## Embeddings

| Date | Model | Dims | Chunk set | # chunks | Embed time (M-series GPU) | Index |
|---|---|---|---|---|---|---|
| 2026-10-23 | BAAI/bge-small-en-v1.5 (local, free) | 384 | section_300 | 15,436 | 169 s (91 chunks/s) | HNSW, cosine |
| 2026-10-23 | BAAI/bge-small-en-v1.5 (local, free) | 384 | fixed_300 | 7,406 | 69 s (107 chunks/s) | HNSW, cosine |

## Retrieval experiments (recall@5 on the eval set)

| Date | Eval set size | Setup (chunking, search, reranker) | Recall@5 | Notes |
|---|---|---|---|---|
| | | | | |

## Answer quality

| Date | Setup | Faithfulness | Correct refusals | Notes |
|---|---|---|---|---|
| | | | | |

## Cost and speed

| Date | Setup | Median latency | p95 latency | Cost per query |
|---|---|---|---|---|
| 2026-10-23 | Vector search only, local Mac, 30 queries, top-5 over 15,436 chunks | 22.8 ms embed + 2.7 ms DB | 37.9 ms embed + 5.1 ms DB | $0 (local model) |
