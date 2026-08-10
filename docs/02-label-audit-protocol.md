# Label Audit Protocol

**Status:** protocol, 2026-08-09
**Depends on:** [01 — How EDINET-Bench's Fraud Labels Were Made](./01-how-edinet-bench-labels-were-made.md)
**Effort:** ~90 minutes of reading, plus setup

---

## 1. The question this answers

EDINET-Bench's fraud labels were assigned by an LLM reading amendment filings. The paper admits three failure modes — honest mistakes counted as fraud, hallucination, and corrections unrelated to the financial statements being swept in — but never measures how often any of them occur.

So nobody knows how good the answer key is.

That matters because **label noise caps the achievable score.** If 15% of the positive class isn't really fraud, no model can exceed the ceiling that imposes, and every published figure — including the 0.73 baseline — is being measured against a partly-wrong key. Before optimising toward a number, we should know how much of that number is reachable.

This protocol produces a measured estimate of positive-label precision, with an interval, and a gold set that makes automated re-labelling possible.

---

## 2. What you are actually reading — and what you are not

**You are not looking at financial statements and deciding whether a company committed fraud.** That is forensic accounting, it takes years of specialist training, and this protocol does not require it.

You are reading the **提出理由** — the "reason for submission" section of the amendment, where the company states in writing why it is correcting its filing. They have already told you what happened. Typical phrasings:

| Stated reason (typical form) | What it is |
|---|---|
| 当社連結子会社における不適切な会計処理が判明したため | Improper accounting at a subsidiary — clearly financial |
| 第三者委員会の調査報告書の受領に伴い、過年度の売上高を訂正するため | Third-party committee investigation, prior-year revenue restated — clearly financial, serious |
| 記載事項に誤記がありましたので訂正いたします | Typographical errors — clerical |
| 役員の異動に伴う記載事項の訂正 | Officer changes — not financial at all |

That last category is exactly the failure mode the paper's own spot-check admits to.

This is reading comprehension over a declarative sentence. It is precisely the task the LLM labeller performed — so the audit compares two readers of the same text, rather than asking you to out-diagnose an auditor.

**Where language genuinely runs out:** companies deliberately use vague wording. 「不適切な会計処理」 covers both a deliberate scheme and a control failure, and that ambiguity is a drafting choice, not a translation problem. The rubric below is built so you never have to resolve it.

---

## 3. The rubric

### Primary axis — is this correction about the financial statements?

Assign exactly one bucket per item.

| Bucket | Definition |
|---|---|
| **A** | Financial-statement correction — revenue, assets, expenses, consolidation, impairment, restatement of reported figures |
| **B** | Non-financial correction — officers, addresses, share counts, typography, formatting, cross-references |
| **C** | Mixed — the amendment covers both |
| **D** | Cannot determine from the 提出理由 alone |

This axis is close to unambiguous, and it directly targets the paper's admitted failure mode.

### Secondary — record which markers are present

These are **factual observations, not judgements**. Tick all that apply:

- [ ] Explicit misconduct vocabulary: 不適切な会計処理 / 粉飾 / 不正
- [ ] 第三者委員会 or 特別調査委員会 involved — a strong factual signal; nobody convenes one over a typo
- [ ] 過年度遡及修正 — retrospective restatement of prior periods
- [ ] Purely clerical language: 誤記 / 誤植
- [ ] Regulatory action referenced (証券取引等監視委員会, 課徴金, etc.)

### Bucket D is a result, not a failure

If a large share of flagged amendments cannot be adjudicated from their stated reason, **that tells us the LLM labeller was also guessing on them.** Report the D-rate prominently. It reframes the exercise honestly: we are not certifying ground truth, we are measuring how much ground truth the source text can support.

---

## 4. Sampling

### For the headline precision number: simple random

- Population: all **534** positive-labelled records.
- Draw **n = 50** by simple random sample, fixed seed, seed recorded.
- Simple random rather than stratified, because the headline figure should be a clean unbiased estimate that needs no reweighting to explain.

### Separately, to find where errors live: keyword-split inspection

Some flagged amendments contain explicit misconduct vocabulary; others don't, and the LLM inferred fraud without it. **Errors will concentrate in the no-keyword group.** After the main sample, look at ~15 items drawn only from the no-keyword subset. This does not feed the headline number — it characterises the failure mode.

### Blinding — do not skip this

The dataset ships an `explanation` field containing the LLM's own reasoning. **Hide the label and the explanation while you classify.** Seeing them first will anchor your judgement and quietly turn a measurement into a confirmation. Prepare the worksheet with 提出理由 text only; join the labels back afterwards.

### Self-consistency check

With a single rater there is no inter-rater reliability. Cheap substitute: after a gap of about a week, re-classify 10 of the 50 without looking at your earlier answers. Agreement rate on those 10 is a floor on how reliable the rubric is. Report it.

---

## 5. Recording

One row per item. Suggested columns:

| Column | Notes |
|---|---|
| `amended_doc_id` | |
| `original_doc_id` | the filing that carries the label |
| `edinet_code` | |
| `filing_year` | |
| `teishutsu_riyu_text` | the raw 提出理由 |
| `bucket` | A / B / C / D |
| `marker_*` | one boolean per secondary marker |
| `note_ja` | free text, in Japanese, on anything ambiguous |

Keep `note_ja` in Japanese. It costs nothing extra and it is the artifact that makes the audit visibly yours.

---

## 6. Computing precision, with an interval

**Definition.** A positive label is *supported* if the amendment is a financial-statement correction.

- Bucket **A** → supported
- Bucket **B** → not supported
- Buckets **C** and **D** → ambiguous

Rather than forcing the ambiguous cases either way, **report a bracket**:

- **Lower bound** — only A counts as supported
- **Upper bound** — A + C + D count as supported
- **D-rate** reported separately and explicitly

A bracketed figure with the undecidable share stated is more honest than a single number that hides a judgement call.

**Interval.** This is a proportion from a small sample, so use a **Wilson score interval** — not the normal approximation, which misbehaves near 0 and 1, and not a bootstrap, which is unnecessary machinery for a single proportion.

Rough sense of what n buys you, at an observed precision around 0.85:

| n | Approximate 95% Wilson interval | Half-width |
|---|---|---|
| 50 | 0.73 – 0.92 | ~±10 pp |
| 100 | 0.77 – 0.91 | ~±7 pp |

**Start with 50.** It's enough to distinguish "the labels are basically fine" from "there's a real problem," which is the decision we actually need to make. Go to 100 only if the first 50 land somewhere ambiguous.

---

## 7. Turning 90 minutes into a re-labelled dataset

The audit is worth more as a calibration set than as an audit. The pipeline:

1. **Hand-label 50** under the rubric above → this is the **gold set**.
2. **Score the released labels** against the gold set → the precision figure from §6.
3. **Build a better labeller** — stronger model, structured output instead of JSON-scraped-from-prose, the rubric above written into the prompt, framed in Japanese.
4. **Score the new labeller against the same gold set.** If it agrees with you at a high rate, it has earned trust.
5. **Re-label all 534 positives automatically**, and report the agreement rate as its measured error bar.

The same 90 minutes then yields a re-derived positive class with a human-validated error rate — a substantially stronger contribution than "we checked 50 and they looked fine."

Keep the gold set frozen and never train or tune a prompt on it. If a prompt gets iterated against these 50, they stop being a measurement and become an overfitting target. Reserve a further 15 items, untouched, as a final check.

---

## 8. What this cannot establish

Stated plainly, because it will be asked:

- **Negative-class error is not measurable this way.** A company that never filed an amendment has no 提出理由 to read. Undiscovered fraud sitting in the negative class is invisible from inside the dataset, and no amount of auditing changes that. It remains a permanent, unquantified limitation of the benchmark.
- **Intent is not established.** The rubric deliberately avoids separating deliberate fraud from control failures, because the source text usually won't support that distinction.
- **Legal fact is not established.** Bucket A means "this amendment corrects the financial statements," not "a court found fraud."
- **One rater.** The self-consistency check bounds rubric reliability; it is not a substitute for a second reader. If the project ever gets a collaborator, a second pass over the same 50 is the first thing to spend them on.

---

## 9. Order of work

1. Extract 提出理由 text for all 534 positives
2. Draw the random 50, seed recorded
3. Build the blinded worksheet — text only, no labels, no explanations
4. Classify (~90 min)
5. Join labels back; compute bracketed precision + Wilson interval + D-rate
6. Inspect the no-keyword subset for failure mode
7. Write up as `03-label-audit-results.md`
8. *Then* decide whether steps 3–5 of §7 are worth doing

Step 7 is a deliverable in its own right, whatever the number turns out to be. A clean measurement that says "the labels are fine" is just as publishable as one that says they aren't — and it's the prerequisite for taking any later score seriously.

---

## Related, but a separate workstream

The classical quantitative forensic-accounting measures — Beneish M-Score, Dechow F-Score, Benford's Law on digit distributions, accruals-quality models — run directly on the BS/PL/CF data already in the dataset, and as far as we can tell nobody has run them on EDINET-Bench. If they beat the 0.68 logistic-regression baseline, that is a result on its own; and a hybrid of quantitative features with LLM narrative reading is a plausible route past 0.73, since the published numbers already suggest the narrative carries signal the ratios don't.

That belongs in its own note. It is not part of the label audit.
