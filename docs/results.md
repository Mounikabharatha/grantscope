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

### CI reproduction (Phase 7, GitHub Actions, CPU only)

| Date | Run | section_300 vector R@5 | section_300 hybrid + reranker R@5 | Gate | Runtime |
|---|---|---|---|---|---|
| 2026-10-25 | [#40180633884](https://github.com/Mounikabharatha/grantscope/actions/runs/40180633884) | 82.3% (R@1 46.8%) | 89.9% (R@1 64.6%) | passed | 36 min (embedding 1,002 s at 15 chunks/s; reranking ~13 s/question on CPU) |

Recall@5 on a fresh CPU machine matches the local Apple-GPU run exactly; recall@1 for vector differs by
one question (46.8% vs 45.6%) from floating-point differences.

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

## Live deployment (Phase 8): Cloudflare Workers + Workers AI + Neon

Deployed at https://grantscope.mounikabharatha.workers.dev (2026-10-25). Same pipeline ported to a
TypeScript Worker: Neon Postgres + pgvector 0.8.6 via Hyperdrive; Workers AI for bge-small-en-v1.5
(CLS pooling), bge-reranker-base, and **@cf/meta/llama-3.1-8b-instruct-fp8** (the non-FP8 Llama 3.1 8B
was retired from Workers AI on 2026-05-30; locally Ollama runs a 4-bit build of the same model).

### Model parity checks before deploying

| Check | Result |
|---|---|
| 30 stored chunk embeddings vs Workers AI (CLS) | cosine similarity 1.0000 (min and mean): no re-embedding needed |
| 10 eval-question embeddings, local vs Workers AI | cosine 1.0000 |
| Reranker, 2 queries x 12 candidates | identical ranking (Spearman 1.000) and identical 0-1 scores (max diff 0.0000). This caught a bug: the first Worker draft applied a sigmoid to already-normalized scores |

### Live evaluation (`scripts/evaluate_live.py`, through the public API)

| Retrieval, 79 questions | R@1 | R@5 | R@10 | MRR | Right grant in top 5 | Median /search latency |
|---|---|---|---|---|---|---|
| vector | 49.4% | 83.5% | 88.6% | 0.625 | 97.5% | 1,286 ms |
| **hybrid + reranker** | 65.8% | **89.9%** | 93.7% | 0.771 | **100%** | 1,751 ms |

Recall@5 for hybrid + reranker is identical to local (89.9%); vector is one question higher (HNSW is
approximate and the Neon index was built separately).

| Answers, 93 questions | Local (Ollama, v2) | **Live (Workers AI FP8)** |
|---|---|---|
| Unanswerable correctly refused | 92.9% (13/14) | **78.6% (11/14)** |
| Answerable answered | 93.7% (74/79) | 92.4% (73/79) |
| Correct of answered (after review) | 95.9% (71/74) | **97.3% (71/73)** |
| Faithful, of all answers shown (after review) | 97.3% (73/75) | **94.7% (72/76)** |
| Quote validity | 96.1% | 95.8% (114/119) |
| Median answer latency | 11.4 s (M1 Pro) | **6.5 s** (generation 5.0 s) |

Reviewed failures on the live site:
- **q080 (trick, NIH R01): hallucinated attribution.** Quoted a nursing grant's "Up to $750,000 per year"
  as the NIH R01 amount. Top reranker score 0.135, above the 0.05 early-refusal cutoff.
- **q081 (trick, DOE SBIR):** USDA SBIR rules presented as DOE's (same failure as locally).
- **q087 (trick, Clean Vessel Act electric charging):** inferred "No" from what the eligible-activities list
  omits instead of refusing.
- **q029 (Region 9 states):** claimed the states aren't listed, then added New Mexico from the model's own
  knowledge (wrong; New Mexico is Region 6). The 8B judge called it correct.
- **q051:** quoted the other NEH Landmarks NOFO's $230,000 (same as locally).
- 6 false refusals (q003, q017, q035, q044, q071, q091).
- The 8B judge marked 5 well-supported answers as unsupported (q021, q048, q060, q062, q065).

Takeaways: retrieval transfers exactly; the hosted FP8 model refuses trick questions less reliably than the
local 4-bit build (3 answered vs 1). The dominant failure is **entity mismatch** (right-looking quote from the
wrong grant/program). A next step would be a check that the cited grant matches the program named in the
question, validated on a fresh set of questions rather than tuned on this one.

## Wrong-grant fix (scope by agency / named grant), 2026-10-25

**Problem:** the quote check proves a quote is real, not that it comes from the program asked about.
Examples: an NIH question answered with a HRSA nursing grant's "$750,000 per year" (q080); DOE SBIR
answered with USDA's rules (q081); the $230,000 of "Landmarks of *American* History..." given for
"Landmarks of History..." (q051).

**Fix (`app/scope.py`, ported to `worker/src/scope.ts`):** before searching,
1. if the question names a federal agency (dictionary of ~25 major funders, acronyms matched
   case-sensitively), search only that agency's grants; if it names only agencies with no grants in
   the corpus, refuse immediately and list the agencies we do have;
2. if the question contains a grant title (>= 75% of the title's words, **in order**), search only the
   most specific matching grant.

**Method:** a new **holdout set** (`eval/holdout.csv`, 35 questions: 16 look-alike grants, 6 regular,
13 agencies/programs not in the corpus) was written and committed (c834f95) **before** the fix code,
and the unfixed system was measured on it first. While building the fix, the original set exposed one
bug (q006: "...pumpout facilities ... Clean Vessel Act" matched the unrelated "Research Facilities Act
Program"); order-aware title matching fixed it. The holdout was not used for any design decision.
Python and TypeScript scope decisions were checked identical on all 128 questions.

| Holdout (35 new questions), local | Before fix | **After fix** |
|---|---|---|
| Unanswerable refused | 84.6% (11/13) | **92.3% (12/13)** |
| Answerable answered | 90.9% (20/22) | 90.9% (20/22) |
| Correct of answered (judge) | 95.0% (19/20) | 95.0% (19/20) |
| Faithful of answered (judge) | 100% (20/20) | 100% (20/20) |
| Retrieval recall@5 | 90.9% | 90.9% |
| Median answer latency | 9.3 s | 5.3 s |

| Original set (93), local | Before (v2, reviewed) | **After (reviewed)** |
|---|---|---|
| Unanswerable refused | 92.9% (13/14) | **100% (14/14)** |
| Answerable answered | 93.7% (74/79) | 93.7% (74/79) |
| Correct of answered | 95.9% (71/74) | **98.6% (73/74)** (q051 fixed; q027 still misleading) |
| Faithful of answered | 98.6% (73/74) | 98.6% (73/74) (q027) |
| Retrieval recall@5 / recall@1 | 89.9% / 64.6% | 94.9% / 70.9%* |

*The original set was used to find the q006 bug, so treat its gains as optimistic; the holdout is the
clean measurement.

| Live site, after fix | Result |
|---|---|
| Holdout: unanswerable refused | 92.3% (12/13) |
| Holdout: answered / correct / faithful | 20/22 answered, 19/20 correct (judge), 20/20 faithful |
| Previously failing live questions (q029, q051, q080, q081, q087) | **4 of 5 fixed**: q080/q081 refused ("My documents don't include grants from..."), q051 now $460,000 from the right NOFO, q029 now lists exactly the PDF's states |

The full 93-question live run was not repeated after the fix, to stay within the Workers AI free daily
allowance.

**Still failing:**
- **h035 "NEH Summer Stipends":** the agency (NEH) is in the corpus but that program isn't, so the
  agency filter keeps NEH grants and the model quotes another NEH program's "$5,000 per month".
  The scope check can't tell "a program we don't have" from "a program named loosely".
- **q087 "Clean Vessel Act electric charging":** inferred "No" from what the eligible-activity list omits.
- **q027:** turns "cost sharing may be waived for..." into a misleading "No...".
- The agency dictionary only covers major funders; a question naming an agency outside it falls back to
  the old behavior.

## Missing-program fix, 2026-10-28

**Problem:** for a program we don't have at an agency we do cover (e.g. "NEH Summer Stipends"), the agency
filter kept that agency's other grants and the model quoted one of them ("$5,000 per month").

**Fix (`app/scope.py`, `worker/src/scope.ts`):** when no grant title matched, find program names in the
question (capitalized phrases containing or followed by Program/Grants/Award/Stipends/Fund/...), drop the
agency name, and refuse unless the name contains or shortens one of our titles, or appears as a phrase in
our documents. The refusal lists the agency's announcements we do have.

**Method:** a new set, `eval/holdout_programs.csv` (23 questions: 11 programs absent from the corpus, 3
mentioned only in passing, 1 lowercase, 8 controls that must still be answered), was committed (69952a4)
before the fix. While building it, the older sets exposed two false refusals ("SBIR/STTR Phase II": keep
names as typed; "Gus Schumacher Produce Prescription Program": accept shortened titles), which were fixed
before the new set was run. Python and TypeScript decisions identical on all 151 questions.

| Program set (23), local | Before | **After** |
|---|---|---|
| Missing programs refused | 46.7% (7/15) | **86.7% (13/15)** |
| Controls answered and correct | 8/8 | **8/8** |
| Median answer latency | 10.2 s | 1.7 s |
| Live site, after | | 13/15 refused, 8/8 controls correct |

| Older sets, local, after | Before (v2 fix) | After |
|---|---|---|
| Holdout (35): unanswerable refused | 12/13 | **13/13** (Summer Stipends fixed) |
| Holdout: correct of answered | 19/20 | 19/20 |
| Original (93): unanswerable refused | 14/14 | 14/14 |
| Original: answered / correct (reviewed) | 74/79, 73/74 | 74/79, 73/74 |
| Retrieval recall@5 (all sets) | unchanged | unchanged |

On the 128 questions behind the resume numbers, after this fix: refusals 27/27 (100%), faithful 93/94
(99%); both up from 96% / 98%.

**Still failing (as predicted when the set was written):**
- p021 "USDA Organic Agriculture Research and Extension Initiative": named in another USDA NOFO, so the
  phrase check counts it as known and the model invents an amount.
- p023 "how much do nurse corps scholarships pay?": lowercase names are not detected.
