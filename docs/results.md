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

### Re-measured on the 79-question set (after q091 became answerable in Phase 6)

| Date | Chunking | Search | R@1 | R@3 | R@5 | R@10 | MRR | Right grant in top 5 |
|---|---|---|---|---|---|---|---|---|
| 2026-10-25 | section_300 | vector | 45.6% | 70.9% | 82.3% (65/79) | 87.3% | 0.602 | 96.2% |
| 2026-10-25 | section_300 | hybrid + reranker | 64.6% | 88.6% | **89.9% (71/79)** | 93.7% | 0.765 | 100% |
| 2026-10-25 | fixed_300 | vector | 29.1% | 51.9% | 63.3% | 77.2% | 0.445 | 94.9% |
| 2026-10-25 | fixed_300 | hybrid + reranker | 58.2% | 82.3% | 86.1% | 92.4% | 0.716 | 100% |

These are the reference numbers for the CI quality gate (Phase 7): the build fails if section_300
recall@5 drops below **79% (vector)** or **87% (hybrid + reranker)**, about two questions under the
measured scores, so CPU-vs-GPU rounding doesn't fail a build but a real regression does.

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

## Answer quality (Phase 6)

Setup: hybrid + reranker top 5 passages -> Llama 3.1 8B (Ollama, local, temperature 0) answers only from
the passages with word-for-word quotes -> every quote checked against the passage it cites; unverified
quotes dropped; no verified quote = refusal. Early refusal if the best reranker score < 0.05 (fixed, not tuned).
Judge for correctness/faithfulness = the same Llama 3.1 8B, then the flagged cases reviewed by hand.

| Run | Unanswerable refused | Answerable answered | Correct (of answered) | Faithful (of answered) | Quote validity | Median latency |
|---|---|---|---|---|---|---|
| v1 (2026-10-24) | 73.3% (11/15) | 94.9% (74/78) | 95.9% (71/74), judge | 91.9% (68/74), judge | 96.3% (103/107) | 11.6 s |
| **v2 (2026-10-24)** | **92.9% (13/14)** | **93.7% (74/79)** | 97.3% (72/74) judge; **95.9% (71/74) after review** | 94.6% (70/74) judge; **98.6% (73/74) after review** | **96.1% (99/103)** | 11.4 s (generation 9.8 s) |

Counting every answer shown to a user (74 answerable + 1 unanswerable that slipped through):
**faithful 73/75 = 97.3%**, after review.

### What changed between v1 and v2 (and why)

- **Answer key fixes, found by the system** (recorded in `eval/questions.csv` reviewer notes):
  - q091 was drafted as unanswerable, but the SDS NOFO page 8 does list scholarship caps ($50,000 dental,
    $40,000 others); my keyword check had missed it. Converted to answerable (now 79 answerable / 14 unanswerable).
  - q004: the Tribal Wildlife NOFO contradicts itself (80 expected awards on page 3, "issue 30 to 40 awards" on
    page 8). Reference updated to accept either.
- **Bug fix:** the model sometimes wrote "this is not mentioned in the passages" while flagging the answer as
  answerable and attaching an unrelated quote (q071, q084, q089). Such text is now treated as a refusal
  (`is_non_answer`, unit-tested on real answers like "not eligible" so they still pass).
- **Judge context:** the faithfulness judge now sees each quote's section heading, as a human checker would.

### Remaining failures (v2, reviewed)

- **q081, hallucinated entity:** asked about the *Department of Energy* SBIR program, it answered with the
  *USDA* SBIR rules (the quote is real, the attribution is wrong). The most serious failure type.
- **q051, wrong grant:** two similar NEH "Landmarks" NOFOs; it quoted the other one's $230,000 instead of $460,000.
- **q027, misleading wording:** "No, the cost share cannot be waived for facilities *not* located in..."
  twists "cost sharing may be waived for facilities in economically distressed communities".
- **q091, partial:** gave the $40,000 cap but not the $50,000 dental cap.
- **5 false refusals** (q003, q008, q044 + 2): the model said "not answerable" despite a relevant top passage
  (score > 0.96), or (q017) quoted only "• Individuals.", which is too short to verify by design.
- The 8B judge made 3 false "unsupported" calls (q060, q062, q065) and missed q027; judge numbers alone are
  not reliable at this model size.

## Cost and speed

| Date | Setup | Median latency | p95 latency | Cost per query |
|---|---|---|---|---|
| 2026-10-23 | Vector search only, local Mac, 30 queries, top-5 over 15,436 chunks | 22.8 ms embed + 2.7 ms DB | 37.9 ms embed + 5.1 ms DB | $0 (local model) |
| 2026-10-24 | hybrid + reranker, local Mac (MPS), 78 eval queries, 15,436 chunks | 1,082 ms | 1,177 ms | $0 (local models). Reranking 30 passages is ~85% of the time; vector alone is ~21 ms. |
| 2026-10-24 | full answer: retrieval + Llama 3.1 8B generation, local M1 Pro, 93 eval questions | 11.4 s | 40 s max | $0 (local models). Generation is ~85% of the time. |
