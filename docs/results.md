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
| 2026-10-24 | section_300 | keyword only (Postgres full-text, OR query, title A / section B / text C weights) | 16.7% | 30.8% | 38.5% | 53.8% | 0.277 | 92.3% | Finds the right grant (92%) but not the paragraph: every chunk of a grant shares its title words. |
| 2026-10-24 | section_300 | hybrid (vector + keyword, RRF k=60, 50 candidates each) | 38.5% | 61.5% | 70.5% | 88.5% | 0.533 | 98.7% | **Worse than vector alone at R@5** (-11.6): the weak keyword list pushes correct passages to ranks 6-10. Better R@10 and right-grant@5. |
| 2026-10-24 | section_300 | vector + reranker (bge-reranker-base on top 30) | 67.9% | 87.2% | 89.7% | 93.6% | 0.783 | 98.7% | Reranker is the big win: R@1 46% -> 68%. Fixed 9 baseline misses, broke 3. |
| 2026-10-24 | section_300 | **hybrid + reranker** (top 30 of hybrid) | 65.4% | 88.5% | **89.7%** | 93.6% | 0.771 | **100%** | **Chosen default.** Same R@5 as vector+rerank (fixes q022 "DERA" subject line, loses q071), right grant always in top 5. |
| 2026-10-24 | fixed_300 | keyword only | 16.7% | 35.9% | 53.8% | 70.5% | 0.316 | 89.7% | |
| 2026-10-24 | fixed_300 | hybrid | 28.2% | 50.0% | 69.2% | 91.0% | 0.452 | 100% | |
| 2026-10-24 | fixed_300 | vector + reranker | 53.8% | 79.5% | 83.3% | 88.5% | 0.676 | 97.4% | |
| 2026-10-24 | fixed_300 | hybrid + reranker | 59.0% | 83.3% | 87.2% | 92.3% | 0.724 | 100% | The reranker shrinks the chunking gap from 18 to 2.5 points. |

### Phase 5 takeaways

- **Baseline -> final: recall@5 82.1% -> 89.7%, recall@1 46.2% -> 65.4%, MRR 0.607 -> 0.771** (section chunks, 78 questions).
- Almost all of the gain comes from the **reranker**. Hybrid search alone *lowered* R@5; combined with the
  reranker it ties vector+reranker on R@5 (one question gained, one lost, which is noise at n=78) but puts
  the right grant in the top 5 for every question and fixes exact-term queries like "DERA National NOFO
  Question" that embeddings miss. Kept hybrid+rerank as the default for robustness on names/IDs/acronyms.
- Settings (RRF k=60, 50 candidates per list, rerank top 30) are standard defaults chosen before running
  the eval, not tuned on it.
- Remaining 8 misses: 6 found the right grant at rank 1 but a different passage. Some may be eval-set
  limits: e.g. q041's top result is the grant's "Additional information on eligibility" section, which
  also partly answers the question but doesn't contain the single evidence quote.

## Answer quality

| Date | Setup | Faithfulness | Correct refusals | Notes |
|---|---|---|---|---|
| | | | | |

## Cost and speed

| Date | Setup | Median latency | p95 latency | Cost per query |
|---|---|---|---|---|
| 2026-10-23 | Vector search only, local Mac, 30 queries, top-5 over 15,436 chunks | 22.8 ms embed + 2.7 ms DB | 37.9 ms embed + 5.1 ms DB | $0 (local model) |
| 2026-10-24 | hybrid + reranker, local Mac (MPS), 78 eval queries, 15,436 chunks | 1,082 ms | 1,177 ms | $0 (local models). Reranking 30 passages is ~85% of the time; vector alone is ~21 ms. |
