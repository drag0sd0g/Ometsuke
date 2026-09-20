# Classical Forensic-Accounting Features on EDINET-Bench

**Depends on:** [02 — What the Dataset Contains](./02-what-the-dataset-contains.md)
**Needs no model.** Every number here comes from the structured `bs` / `pl` / `cf` sheets.

Beneish's M-score is the standard quantitative screen for earnings manipulation. As far
as we can establish it has not been run on EDINET-Bench. It should be, because a language
model scoring 0.73 on a task an eight-ratio formula also solves is a much less interesting
result than it first appears.

**It does not solve it. The M-score scores ROC-AUC 0.438 — below chance, with the
interval excluding 0.5.** What follows is that result and the checks it survived.

---

## 1. Who can be scored at all

The M-score needs twelve accounts in two consecutive years. Japanese filers label these
consistently enough for that to be mostly achievable, but not always.

| | |
|---|---|
| Training rows | 865 |
| Computable | **591 (68.3%)** |

Blocked by, in order: `net_income` (90 rows), `sales` (89), `receivables` (62),
`cogs` (17), `depreciation` (8), `noncurr_liab` (6), `sga` (1), `ppe` (1).

Two decisions shape that number. **Trade receivables resolve 受取手形及び売掛金 and 売掛金
as mutually exclusive** — the former means "notes *and* accounts receivable" and already
contains the latter — while 電子記録債権, a separate instrument, is added on top. And
有価証券 was excluded from the asset-quality index: it is present in only 12.7% of rows, and
including it drops coverage from 68.3% to **8.0%** while adding nothing the 1999
formulation requires.

### A correction, 2026-09-20

An earlier version of this document reported **0.436** with DSRI among the inverted
indices. Receivables were being summed across 受取手形及び売掛金, 売掛金 and 電子記録債権 —
but the first of those means "notes **and** accounts receivable" and already contains the
second. 55 training filings report both. For 39 the same labels appear in both years and
the error cancels inside DSRI, which is a ratio of ratios; for **16 the labels differ
between years**, so it does not.

Fixed by treating 受取手形及び売掛金 and 売掛金 as mutually exclusive alternatives while
still adding 電子記録債権, a genuinely separate instrument. The composite moved 0.436 →
0.438, immaterially. **DSRI's interval now touches 0.5** and no longer clears the bar,
which narrows the finding from two inverted indices to one.

### The computable subset is not a random sample

| | n | fraud rate | mean fiscal year |
|---|---:|---:|---:|
| computable | 591 | **51.8%** | 2019.60 |
| dropped | 274 | **38.7%** | 2017.95 |

Filings whose financial statements parse completely are **13 percentage points more
likely to carry a fraud label**, and are a year and a half more recent. This partly
answers an open question from `docs/02`: parse failures correlate with filing year, and
also with the label itself.

**Consequence.** Any score computed here describes a population with a different base
rate and a different era distribution from the one the published baselines were measured
on. Comparisons against the published 0.68 and 0.73 are **not like-for-like**, and are not
made below. The comparison that is made is against a control computed on exactly these
591 rows.

---

## 2. The result

All intervals are 95% percentile bootstrap, 2,000 draws, **resampled by company** (400
companies behind 591 filings), seed 42.

| | ROC-AUC | 95% CI |
|---|---:|---|
| **Beneish M-score** | **0.438** | [0.389, 0.491] |
| Filing year alone (control) | 0.594 | [0.538, 0.650] |

**Paired bootstrap, same 591 items: M-score − era = −0.156, 95% CI [−0.234, −0.081].**
The interval excludes zero. The M-score is not merely uninformative here; it is
significantly worse than knowing nothing but the filing's date.

At Beneish's own cutoff the picture is muddier, which is itself worth recording: 11.8% of
positives and 7.4% of negatives exceed M > −1.78. The flag rate runs in the expected
direction even though the continuous score runs against it — consistent with a correct
extreme tail sitting on top of an inverted bulk.

---

## 3. Two explanations ruled out

**It is not an era artifact.** The correlation between the M-score and filing year is
**+0.065** — effectively nothing — while the correlation between label and year is −0.170.
Whatever the M-score is tracking, it is not the right-censoring that makes date alone
worth 0.635 on the test split.

**It is not outliers.** Ratio indices like DSRI can take extreme values when a denominator
is small, which is the obvious suspicion. But ROC-AUC depends only on rank order and is
invariant under any monotonic transform, so winsorising or log-scaling cannot change it by
construction. The observed distribution is in any case well behaved: p05 −3.42, median
−2.54, p95 −1.26.

---

## 4. Which index is doing it

Per-index AUC on the same rows. Values above 0.5 mean a higher index value is associated
with the fraud label, as Beneish intends.

| index | ROC-AUC | 95% CI | |
|---|---:|---|---|
| DSRI — days sales in receivables | 0.458 | [0.417, 0.500] | |
| GMI — gross margin | 0.507 | [0.467, 0.549] | |
| AQI — asset quality | 0.463 | [0.423, 0.505] | |
| SGI — sales growth | 0.454 | [0.407, 0.504] | |
| DEPI — depreciation rate | 0.473 | [0.429, 0.515] | |
| SGAI — SG&A | 0.545 | [0.498, 0.590] | |
| **TATA — total accruals to assets** | **0.428** | [0.377, 0.481] | **inverted** |
| LVGI — leverage | 0.532 | [0.487, 0.575] | |

Seven of the eight straddle 0.5. **Only TATA does not**, and it carries by far the largest
coefficient in the composite (4.679), which is why the M-score lands where it does rather
than merely near chance.

**Caveat that must travel with this table:** eight indices were tested and one cleared a
95% interval — which is roughly what chance alone produces from eight tests, and no
correction for multiple comparisons has been applied. TATA is worth taking seriously on
the strength of its effect size and its weight in the composite, not on its interval.

---

## 5. Why accruals might run backwards here — hypotheses, not findings

TATA is (net income − operating cash flow) / total assets. Beneish's premise is that
manipulated earnings show up as income unsupported by cash. Here, filings later amended
for accounting reasons have *lower* accruals than those that were not.

Three candidate explanations, none tested:

1. **The label is not "earnings were manipulated."** It is "this filing was later amended,
   and an LLM reading the amendment's 提出理由 judged the reason to be accounting
   misconduct." That set includes restatements with no earnings-inflation motive at all.
2. **循環取引.** Circular or round-trip trading is a characteristically Japanese pattern in
   which fictitious sales are settled by cash moving in a loop between colluding parties.
   It inflates revenue *and* operating cash flow together, which would leave accruals
   unremarkable or depressed — the opposite of the accrual signature Beneish was built to
   catch. If this is a meaningful share of the positive class, an accruals-based screen
   should fail exactly as observed.
3. **Coefficients estimated on US filings in the 1990s.** They are applied here unmodified.
   Re-estimating them on Japanese data is a different exercise, and would need a held-out
   split to mean anything.

Hypothesis 2 is the one worth pursuing, because it is checkable against the amendment
texts already recovered and would be a substantive statement about what this benchmark's
positive class actually contains.

---

## 6. What this does and does not establish

**Does:** on the 68.3% of training filings where it can be computed, the Beneish M-score
carries no usable signal for EDINET-Bench's fraud label, and ranks filings slightly worse
than their date does. A quantitative screen does not trivially solve this benchmark.

**Does not:** say anything about the published 0.68 or 0.73, which were measured on a
different population. Nor does it establish that Japanese accounting fraud is undetectable
by ratios — only that *these* ratios, with *these* coefficients, against *this* label, do
not work.

---

## 7. Reproducing

```python
from ometsuke.forensics import beneish, coverage

coverage(rows)          # the selection table in §1
beneish(row).m_score    # None, with .unavailable naming the missing account
beneish(row).indices    # the eight indices individually
```

Nothing is imputed: a missing account yields a missing score, and a zero denominator
yields a missing index rather than an infinity that would sum into a finite-looking
composite. The known-answer tests in `tests/test_forensics.py` pin the arithmetic — with
both years identical and no accruals, the composite must equal exactly −2.48.
