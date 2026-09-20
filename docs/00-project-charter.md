# Ometsuke — Project Charter

What this project is, and the constraints that fix its scope.

---

## The problem

[EDINET-Bench](https://huggingface.co/datasets/SakanaAI/EDINET-Bench) (Sakana AI, ICLR 2026)
measures Japanese accounting-fraud detection from annual reports (有価証券報告書). The best
published result is ROC-AUC 0.73 / MCC 0.32 (Claude 3.5 Sonnet with narrative text),
against 0.68 / 0.17 for logistic regression.

Models are asked to judge **one filing in isolation**. Fraud rarely sits inside a single
report; it shows up as drift *between* filings, and against what the company was
simultaneously telling the market elsewhere.

## The thesis

The Herculean agentic-finance benchmark (arXiv 2605.14355, May 2026) found that agents do
reasonably on trading and market-insight workflows but *"struggle substantially on Hedging
and Auditing, where long-horizon coordination, state consistency, and structured
verification are critical."*

Those are distributed-systems problems, not prompting problems. So the infrastructure
layer is the claim, not a garnish on one:

> Agentic auditing doesn't fail on reasoning. It fails on state consistency and
> verification. Here is a system engineered for those properties, and here is what it
> scores on an auditing benchmark that has no agentic entry.

## Constraints

Fixed. Proposals that violate them get rejected without further analysis.

- **Local inference only.** No paid model APIs, no spend. An open-weight model scoring
  differently from a published figure measures the model, not the benchmark — so what
  this offers is an open-weight evaluation with company-clustered intervals,
  reproducible by anyone with no API budget.
- **No manual classification.** Nothing in the plan may depend on a human reading and
  labelling documents by hand.
- Roughly 2–3 hours per week, single contributor.

---

## Measured capacity

*M5 Max, 128 GB, `qwen3.5-122b-ctx` at 131,072 context.*

| | |
|---|---|
| Prefill | 782 tok/s |
| Generation | 49 tok/s |
| Dev subset, structured fields (61 items) | 25 min |
| Test split, full text (224 items) | ~3 h |
| Full dataset, full text (1,089 items) | ~15 h — one overnight run |

Filings run ~27k tokens at the median and ~62k at the maximum, so every one fits in
context with roughly 2× headroom. **Truncation is not required and must not be introduced
silently.** Runs are sequential; concurrency is the untested lever, since generation is
bandwidth-bound and parallel requests would amortise the same weight reads.

---

## Measurement rules

The harness itself is described in the README. Two rules govern every number it produces.

**Error bars are the deliverable.** ROC-AUC and MCC are trivial to compute. The test split
is 224 items and published MCC is 0.32 — at that n, an apparent improvement to 0.38 is
indistinguishable from noise. Use a paired bootstrap when comparing two systems on the
same items.

**Always resample companies, not filings** ([02](./02-what-the-dataset-contains.md) §3).
The known-answer check is that a clustered interval must come out *wider* than a naive one
on the same data.

---

## Workstreams

| | | Needs |
|---|---|---|
| A | **Classical forensic-accounting features.** Beneish's M-score is **done** — ROC-AUC 0.436, below chance ([03](./03-forensic-accounting-features.md)). Dechow F-Score, Benford's Law and Jones-model accruals remain. | No model calls |
| B | **Open-weight baseline** on dev and test splits, company-clustered intervals | Local inference |
| C | **Era ablation** — how much of a text-based score is recoverable from era cues alone | Local inference |
| D | **Prompt variants** — score elicitation, the auditor framing, instruction language | Local inference |
| E | **The agent** — multi-step investigation, temporal diffing, cross-source corroboration | Local inference |
| F | **Event-sourced replay and per-run accounting** | Harness only |

## Open questions

- What is the real base rate of fraud-corrected annual reports among Japanese listed
  companies? Computable from the local metadata archive.
- Why does the accruals index run backwards? The 循環取引 hypothesis in
  [03](./03-forensic-accounting-features.md) §5 is checkable against the recovered
  amendment texts.
- Do parse failures also track company size or accounting standard? Filing year and the
  label are already known to ([03](./03-forensic-accounting-features.md) §1).
- Can an out-of-time split have a positive class at all, given the right-censoring in
  [02](./02-what-the-dataset-contains.md) §2?

## Sources

- **EDINET-Bench** — Sugiura, Ishida, Makino, Tazuke, Nakagawa, Nakago, Ha. Sakana AI, ICLR 2026.
- **Herculean** — agentic finance benchmark, arXiv 2605.14355, May 2026.
- **EDINET API specification** — ESE140206.pdf, for the ten-year retention rule.
