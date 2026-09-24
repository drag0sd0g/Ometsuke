# Narrative Sections: A Train Effect That Did Not Replicate

**Depends on:** [05 — An Open-Weight Baseline](./05-open-weight-baseline.md)
**See also:** [07 — Conclusion](./07-conclusion.md)
**Runs:** `95662f504aae4384`, `5f7977a228a24bc6` (2026-09-23);
held-out test and controls (2026-09-24)

Everything in [05](./05-open-weight-baseline.md) read the structured sheets. Three prompt
variables were tested there and all three returned tight nulls on ranking. This document
changes the **input** instead, and asks:

1. Does narrative disclosure beat financial statements?
2. Does seeing the *prior year's* disclosure help — the premise this project was built on?

**On the training split the first looked like a clear yes: +0.086, interval excluding
zero. It did not survive the held-out test split (§2a). The second is a flat null, and a
later control showed the extra year is inert while the instruction to compare is mildly
harmful (§3a).**

---

## 1. What was read

Two sections, pulled from the XBRL by element name — no layout parsing, no heuristics:

| section | element |
|---|---|
| business risks (事業等のリスク) | `jpcrp_cor:BusinessRisksTextBlock` |
| segment notes (セグメント情報) | `jpcrp_cor:NotesSegmentInformationEtcConsolidatedFinancialStatementsTextBlock` |

**Both years come from EDINET, extracted identically.** The benchmark's own `text` field is
deliberately unused: it is Sakana's extraction, and diffing it against ours would measure
the extraction difference as much as the filing difference.

Two runs, differing *only* by whether the prior year is present and the instruction to
compare — a test asserts the templates are otherwise byte-identical:

| variant | input |
|---|---|
| `sections-current` | the two sections, current year only — **the control** |
| `sections-prior` | the same sections for both years, plus instructions to compare them |

Neither carries the auditor framing, which [05](./05-open-weight-baseline.md) §3 measured
as a calibration switch with no effect on ranking; omitting it from both keeps it out of
the comparison.

### Who could be included

566 of 865 training filings have a retrievable prior year — the ten-year wall removes the
rest ([02](./02-what-the-dataset-contains.md) §5). Of those, 533 have both sections present
in both years. The 33 dropped are label-biased (24.2% fraud against 45.4% among those kept),
plausibly because single-segment companies file no segment note.

**All comparisons below are restricted to the 529 filings scored by every run**, so the
input change is never confounded with a change of population.

---

## 2. On the training split, narrative text beat the financial statements

On those 529 filings (45.4% fraud):

| input | ROC-AUC | 95% CI |
|---|---:|---|
| structured sheets (`baseline`) | 0.562 | [0.519, 0.604] |
| filing year alone | 0.590 | [0.533, 0.647] |
| **risk + segment narrative** | **0.648** | **[0.599, 0.697]** |

> **sections-current − baseline = +0.086, 95% CI [+0.033, +0.137].**
> **The interval excludes zero.**

This was the first intervention in the project to produce a difference rather than a null,
and MCC roughly doubled alongside it, 0.141 → 0.270. **§2a is what happened when it was
taken to held-out data.**

Against the era control the gap is +0.059, CI [−0.009, +0.125] — positive, but the interval
still grazes zero. **So narrative text is measurably better than the financial statements;
whether it is better than knowing the filing's date is not yet established.** That
distinction matters and should not be blurred.

### 2a. It did not replicate on held-out data

The test split was held back for exactly this, and spent once — on a configuration fixed
before any decomposition was run, so nothing learned afterwards could influence it.

| 162 test filings, paired, 51.2% fraud | ROC-AUC | 95% CI |
|---|---:|---|
| structured sheets | 0.597 | [0.520, 0.672] |
| risk + segment narrative | 0.594 | [0.490, 0.686] |

> **narrative − structured = −0.004, 95% CI [−0.111, +0.100].**

The train effect of +0.086 is absent. **The finding below did not replicate, and the
section headline has been changed accordingly.**

**Stated fairly in both directions.** The test interval is ±0.10 against ±0.05 on train —
only 162 filings paired, after the ten-year wall removed 48 of the 224 and section gaps a
few more. It therefore cannot *exclude* an effect of +0.09 either. The honest statement is
that the train result did not replicate and the held-out data lacks the power to settle
it, not that the effect is disproven.

**Why the held-out set is smaller, and biased.** The 48 unreachable test filings have mean
FY 2015.3 and 64.6% fraud, against 51.7% among the 176 that survive — the wall removes
positives preferentially here as everywhere else
([02](./02-what-the-dataset-contains.md) §5).

---

## 3. The prior year does not help

| | ROC-AUC | 95% CI |
|---|---:|---|
| `sections-current` | 0.648 | [0.599, 0.697] |
| `sections-prior` | 0.613 | [0.560, 0.663] |

> **sections-prior − sections-current = −0.035, 95% CI [−0.074, +0.006]** on 532 shared
> filings — indistinguishable, with a negative point estimate.

Doubling the context and asking explicitly about drift — risks appearing or disappearing,
segments redrawn, whether changes are explained — did not improve ranking, and the central
estimate points slightly the wrong way.

**What this does not show.** That temporal comparison is worthless. Only that *this*
operationalisation of it — two sections, one prior year, a single prompt asking the model
to compare — does not recover this benchmark's labels. A richer comparison (more years,
more sections, a cross-check against timely disclosures or price data) is untested.

**What it does show.** The cheapest version of the project's central hypothesis, the one
requiring no agent framework at all, returns a null on 532 filings with a tight interval.
That is worth knowing before building anything more elaborate on the same premise.

### 3a. The control, and what it showed

That caution was tested. `sections-both-quiet` presents both years with **no** instruction
to compare — separating "more context" from "told to weigh change".

| 531 train filings, paired | ROC-AUC | 95% CI |
|---|---:|---|
| `sections-current` (one year) | 0.647 | [0.598, 0.694] |
| `sections-both-quiet` (two years, quiet) | **0.648** | [0.596, 0.698] |
| `sections-prior` (two years, told to compare) | 0.612 | [0.561, 0.662] |

> **two years vs one: +0.001, CI [−0.039, +0.040]** — flat, with a tight interval.
> **instruction vs quiet: −0.036, CI [−0.077, +0.003]**; vs one year: −0.035.

**The prior year is inert. The instruction is what costs.** Two independent comparisons
give the same direction and magnitude. Directing the model's attention toward change pulls
it away from whatever it was already using — which is why the point estimate came out
negative rather than merely flat.

### 3b. Which section carries what

| 532 train filings | ROC-AUC | 95% CI |
|---|---:|---|
| both sections | 0.647 | [0.599, 0.696] |
| risks only | 0.615 | [0.555, 0.677] |
| segments only | 0.589 | [0.532, 0.644] |

Only segments-vs-both excludes zero (−0.057 [−0.109, −0.004]); risks-vs-both does not, nor
does risks-vs-segments. **There is no clean "risk language carries it" story** — the
sections are individually weak and only marginally better combined. Given §2a, this is
best read as noise around a small or absent effect rather than real structure.

---

## 4. Where this leaves the five results

| intervention | effect on ranking |
|---|---|
| auditor framing | −0.004 [−0.037, +0.028] |
| score elicitation | −0.008 [−0.038, +0.024] |
| instruction language (dev only) | worse on every axis |
| input: narrative vs statements (**train**) | +0.086 [+0.033, +0.137] |
| input: narrative vs statements (**held out**) | **−0.004 [−0.111, +0.100]** |
| prior-year context, quiet | +0.001 [−0.039, +0.040] |
| instruction to compare | −0.035 [−0.074, +0.004] |
| risks only vs both sections | −0.032 [−0.085, +0.018] |

**Six interventions. One looked like an effect on the training split and did not survive
the held-out one.** See [07](./07-conclusion.md).

---

## 5. Reproducing

```bash
uv run python scripts/build_prior_year_map.py       # pair filings with their prior year
edinet uv run python scripts/download_prior_years.py --column doc_id
edinet uv run python scripts/download_prior_years.py --column prior_doc_id
uv run python scripts/extract_sections.py           # -> data/section-pairs.jsonl
uv run ometsuke run --split train --pairs data/section-pairs.jsonl --prompt sections-current
uv run ometsuke run --split train --pairs data/section-pairs.jsonl --prompt sections-prior
```

About 2h20m and 3h40m respectively on an M5 Max, entirely local. 1,131 EDINET documents,
103 MB, no failures.
