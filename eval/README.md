# Evaluation set

`questions.csv` is the exam that every retrieval and answer-quality number in
`docs/results.md` is measured on.

| Column | Meaning |
|---|---|
| `type` | `answerable`, or `unanswerable` (the system should refuse) |
| `category` | eligibility, amount, deadline, cost_share, allowable, ... |
| `opportunity_id`, `grant` | the grant whose PDF contains the answer |
| `page` | page in the PDF, for checking by hand |
| `evidence` | a short exact quote from the PDF that answers the question. A retrieved chunk is correct if it is from the right grant **and** contains this quote. Blank = finding the right grant is enough (discovery questions). |
| `answer` | the expected answer, for checking generated answers in Phase 6 |
| `status` | `draft` → change to `keep`, `fix`, or `delete` after review |

## Reviewing

Easiest: `python scripts/review_eval.py` shows one question at a time, opens
the PDF at the right page in Chrome, and saves k/f/d answers into the CSV.

Or by hand:

1. Open `questions.csv` in Google Sheets, Numbers, or Excel.
2. For each row, open the PDF at `data/raw/<opportunity_id>.pdf` on that page
   and check that the evidence and answer are right.
3. Set `status` to `keep`, `fix` (and explain in `reviewer_notes`), or `delete`.
4. Add your own questions at the bottom, especially ones phrased the way a
   real applicant would ask.
5. Run `python scripts/check_eval_set.py` to confirm every quote is found.

Rules: questions are written from reading the PDFs, never from search
results (that would bias the exam toward our own search). Once the baseline
is measured, don't edit questions to make a score go up.
