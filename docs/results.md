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

## Evaluation set

| Date | Questions | Review | Notes |
|---|---|---|---|
| 2026-10-24 | 93 (78 answerable, 15 unanswerable) from 37 grants, all 6 agencies | All evidence quotes and pages machine-verified against the PDFs; 20-question human spot-check spread across agencies: 20/20 correct | Questions written from reading the PDFs, not from search results |

## Retrieval experiments (78 answerable questions)

Recall@k = share of questions where a chunk from the right grant containing the
evidence quote is in the top k. One question = 1.3 points, so differences of a
few points are noise.

| Date | Chunking | Search | R@1 | R@3 | R@5 | R@10 | MRR | Right grant in top 5 | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-24 | section_300 | vector (bge-small, HNSW) | 46.2% | 71.8% | **82.1%** | 87.2% | 0.607 | 96.2% | **Baseline.** 14 misses: 10 found the right grant at rank 1 but ranked the wrong passage first; 2 (q022 "DERA", q032 "SNEP") are acronyms the embedding doesn't match. |
| 2026-10-24 | fixed_300 | vector (bge-small, HNSW) | 29.5% | 52.6% | 64.1% | 76.9% | 0.448 | 94.9% | Section-aware chunking beats fixed by +18 points R@5, mostly on eligibility (74% vs 42%), process (83% vs 17%) and allowable-cost questions (86% vs 43%). Fixed is slightly better on amounts and deadlines. |

## Answer quality

| Date | Setup | Faithfulness | Correct refusals | Notes |
|---|---|---|---|---|
| | | | | |

## Cost and speed

| Date | Setup | Median latency | p95 latency | Cost per query |
|---|---|---|---|---|
| 2026-10-23 | Vector search only, local Mac, 30 queries, top-5 over 15,436 chunks | 22.8 ms embed + 2.7 ms DB | 37.9 ms embed + 5.1 ms DB | $0 (local model) |
