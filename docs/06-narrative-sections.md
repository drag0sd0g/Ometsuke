# Narrative Sections Beat Financial Statements — and the Prior Year Does Not Help

**Depends on:** [05 — An Open-Weight Baseline](./05-open-weight-baseline.md)
**Runs:** `95662f504aae4384` (sections-current), `5f7977a228a24bc6` (sections-prior) — 2026-09-23

Everything in [05](./05-open-weight-baseline.md) read the structured sheets. Three prompt
variables were tested there and all three returned tight nulls on ranking. This document
changes the **input** instead, and asks two questions:

1. Does narrative disclosure beat financial statements?
2. Does seeing the *prior year's* disclosure help — the premise this project was built on?

**Yes to the first, decisively. No to the second.**

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

## 2. Narrative text beats the financial statements

On those 529 filings (45.4% fraud):

| input | ROC-AUC | 95% CI |
|---|---:|---|
| structured sheets (`baseline`) | 0.562 | [0.519, 0.604] |
| filing year alone | 0.590 | [0.533, 0.647] |
| **risk + segment narrative** | **0.648** | **[0.599, 0.697]** |

> **sections-current − baseline = +0.086, 95% CI [+0.033, +0.137].**
> **The interval excludes zero.**

This is the first intervention in the project to produce a difference rather than a null.
MCC roughly doubles alongside it, 0.141 → 0.270.

Against the era control the gap is +0.059, CI [−0.009, +0.125] — positive, but the interval
still grazes zero. **So narrative text is measurably better than the financial statements;
whether it is better than knowing the filing's date is not yet established.** That
distinction matters and should not be blurred.

The direction is consistent with the two other things known about this benchmark:
Beneish's ratios score *below* chance ([03](./03-forensic-accounting-features.md)), and
prompt wording moves nothing. The signal that exists here is in what companies **write**,
not in what they report numerically.

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

**One caution on interpretation.** The prior-year prompt also *instructs* the model to
weigh change. If change is weakly informative here, that instruction dilutes attention
away from whatever in the current year was working — which would explain a negative point
estimate rather than a flat one. Separating "more context" from "told to compare" needs a
third variant: both years present, no comparison instruction. Untested.

---

## 4. Where this leaves the five results

| intervention | effect on ranking |
|---|---|
| auditor framing | −0.004 [−0.037, +0.028] |
| score elicitation | −0.008 [−0.038, +0.024] |
| instruction language (dev only) | worse on every axis |
| **input: narrative vs statements** | **+0.086 [+0.033, +0.137]** |
| prior-year context | −0.035 [−0.074, +0.006] |

**Four nulls and one effect, and the effect is the input.** Every attempt to move the
number by changing how the model is *asked* failed with a tight interval; the one attempt
to change what it *reads* succeeded.

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
