# An Open-Weight Baseline on EDINET-Bench

**Depends on:** [02 — What the Dataset Contains](./02-what-the-dataset-contains.md)
**Runs:** `ecf2a3b549fb4623` (baseline), `780b1b07424f4e53` (no-cpa), 2026-09-20;
`436a10b05e804ad5` (anchored), 2026-09-23

The published leaderboard for this benchmark is frontier-model only. This is the first
evaluation of it on open weights, with intervals that resample companies rather than
filings, reproducible by anyone with a large enough laptop and no API budget.

Three questions, all answered on the 865-filing training split:

1. How well does an open-weight model do, measured honestly?
2. Does the published prompt's auditor framing affect the result?
3. Does forcing a graded score, rather than a near-degenerate one, lift it?

**It beats chance and not the calendar. The prompt changes calibration enormously and
ranking not at all — on all three variables tested.**

---

## 1. What was run

| | |
|---|---|
| Model | `qwen3.5-122b` Q4_K_M, weights `sha256-93c83617a4056…` |
| Sampling | temperature 0, seed 42, 131,072 context, thinking suppressed |
| Input | `summary` + `bs` + `pl` + `cf`. **`meta` excluded** — it carries 当事業年度終了日 |
| Split | train, 865 filings from 603 companies, 47.6% fraud |
| Intervals | 2,000-draw percentile bootstrap, **resampled by company**, seed 42 |

Three runs, differing only in the prompt:

| run | prompt | wall clock | median latency | median output |
|---|---|---|---|---|
| `ecf2a3b549fb4623` | `baseline` — the published text verbatim | 09:37 → 14:33 | 19.2 s | 698 tok |
| `780b1b07424f4e53` | `no-cpa` — that text minus one sentence | 14:33 → 18:30 | 15.7 s | 489 tok |
| `436a10b05e804ad5` | `anchored` — baseline plus six calibration bands | 07:35 → 12:05 | 18.6 s | 585 tok |

The sentence removed in `no-cpa`:

> The report has been verified by a certified public accountant, and the numerical values
> are consistent and correct from a calculation perspective. Therefore, please focus your
> analysis on non-numerical inconsistencies or logical red flags that could suggest fraud.

Failures: **3, 1 and 4 of 865** — 0.3% across all three, nearly all from output
truncation. The scored subsets carry a 47.6% fraud rate against 47.6% in the full split,
so the dropouts introduce no measurable bias. (On the 61-filing dev split they did: a
tighter output budget clipped long answers, and the clipped filings were twice as likely
to be positive.)

---

## 2. The result

| | ROC-AUC | 95% CI | MCC | 95% CI |
|---|---:|---|---:|---|
| `baseline` | **0.550** | [0.515, 0.582] | 0.141 | [0.067, 0.216] |
| `no-cpa` | 0.545 | [0.506, 0.587] | 0.102 | [0.021, 0.186] |
| **filing year alone** | **0.594** | [0.548, 0.640] | — | — |

**The model extracts real signal.** Baseline's interval excludes 0.5, so this is not a
coin flip — an open-weight model reading Japanese financial statements does better than
chance, and that can now be stated with confidence.

**It does not beat the date.** Paired bootstrap on the same items:

> **model − filing year = −0.044, 95% CI [−0.105, +0.016]** — straddles zero.

After five hours of inference over 862 annual reports, the model ranks filings no better
than sorting them by 当事業年度終了日.

This measures at scale what [02](./02-what-the-dataset-contains.md) §4 argued
analytically. The right-censoring is not a theoretical concern about the benchmark; it is
the benchmark's dominant recoverable signal.

---

## 3. One sentence is a calibration switch

Removing the auditor framing changes accuracy by nothing measurable:

> **no-cpa − baseline = −0.004, 95% CI [−0.037, +0.028]** on 861 shared filings.

That is a **tight null**, not a small-sample shrug — the interval is narrow enough to say
the effect is close to zero rather than merely unproven.

But the model's posture inverts:

| score | `baseline` | `no-cpa` |
|---:|---:|---:|
| 5 | — | 3 |
| **15** | 180 | **518** |
| **85** | **631** | 314 |
| 92 | — | 2 |
| 95 | 51 | 27 |
| | 73% called suspicious | 60% called clean |

**338 filings move from "suspicious" to "clean" on the strength of one deleted sentence.**
MCC follows — 0.141 → 0.102 — because MCC depends on where the threshold falls. AUC does
not, because it reads only the order.

**The consequence for anyone using this benchmark.** The published prompt's auditor
framing materially affects every threshold-based metric — accuracy, precision, recall, F1,
MCC — while leaving rank-based metrics untouched. A reported F1 on EDINET-Bench is partly
a report about that sentence. As far as we can establish this has not been documented.

It is also visible in the runtime: `no-cpa` produced a median of 489 output tokens against
baseline's 698, and finished 59 minutes sooner. Told the numbers are already verified, the
model writes more.

---

## 4. Score granularity is not the ceiling — tested and refuted

**An earlier version of this section concluded that a near-degenerate score was capping
the result, and called granularity "the only lever with real headroom behind it." A third
run disproves that.**

`anchored` asks for a precise calibrated value rather than a round one, with six named
bands. Everything else is byte-identical to `baseline`.

| | distinct values | most common | ROC-AUC | 95% CI |
|---|---:|---|---:|---|
| `baseline` | 3 | 85 at 73% | 0.550 | [0.515, 0.582] |
| `no-cpa` | 5 | 15 at 60% | 0.545 | [0.506, 0.587] |
| **`anchored`** | **9** | **82 at 30%** | **0.541** | [0.498, 0.584] |

**The instruction worked.** Three distinct values became nine, and the dominant value fell
from holding 73% of filings to 30%. The degeneracy really was a reporting artefact, and it
is now gone.

**The ranking did not move.**

> **anchored − baseline = −0.008, 95% CI [−0.038, +0.024]** on 858 shared filings.

Tripling the resolution changed AUC by less than one hundredth, well inside noise.

**What that rules out.** A three-valued score does mechanically cap a ROC curve at three
points — that part was right. What was wrong was inferring that a better ranking sat
underneath, suppressed by the reporting scale. It does not. Given a finer scale, the model
spreads the *same* ordering across more values.

This is what `prompts.py` warned about when the variant was written: *the instruction to
spread is itself leading — it can manufacture variance without adding information.* Now
measured rather than suspected.

### The prompting question is closed

Three variables, three full sweeps, 2,587 filings:

| variable | effect on calibration | effect on ranking |
|---|---|---|
| auditor framing (`no-cpa`) | large — 338 filings flip class | **−0.004 [−0.037, +0.028]** |
| score elicitation (`anchored`) | large — 3 → 9 distinct values | **−0.008 [−0.038, +0.024]** |
| instruction language (`japanese`, dev only) | worse on every axis | not measured at scale |

Every interval is tight and every one straddles zero. This is not "too small to tell" —
it is **the prompt does not affect ranking on this task**. Whatever holds the model near
0.55 is not how it is asked.

Which leaves the input. A single annual report judged in isolation may simply not contain
what is needed — the premise this project was built on, now supported by three independent
failed attempts to move the number any other way.

---

## 5. What this does and does not establish

**Does.** On 862 filings with company-clustered intervals, an open-weight 122B model
scores ROC-AUC 0.550 [0.515, 0.582] on EDINET-Bench's structured fields — better than
chance, statistically indistinguishable from filing date alone. Three independent prompt
interventions each shift calibration sharply and leave ranking unmoved, with tight
intervals. Forcing a graded score tripled the number of distinct values and changed
nothing, so near-degenerate output was a symptom rather than the cause.

**Does not.** Say anything about the published 0.73. That figure is Claude 3.5 Sonnet with
narrative text; this is an open-weight model on structured fields. Different model,
different input, not a comparison. Nor does it establish what the model would do given the
narrative text — a single dev-scale run suggested better class separation but more
concentrated scores, and that remains untested at this scale.

---

## 6. Reproducing

```bash
uv run ometsuke run --split train --prompt baseline
uv run ometsuke score <run_id> --split train
uv run ometsuke distribution <run_id> --split train
```

About 5 hours on an M5 Max with 128 GB, entirely local. Every run records the weights
digest, the SHA-256 of the prompt text, the input fields, the dataset revision and the git
SHA, so a number can be traced to exactly what produced it — and `ometsuke replay` will
re-derive it from recorded responses without calling a model at all.
