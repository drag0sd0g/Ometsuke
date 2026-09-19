# Ometsuke — Project Charter

What this project is, what it claims, and the constraints that fix its scope.

---

## The problem

[EDINET-Bench](https://huggingface.co/datasets/SakanaAI/EDINET-Bench) (Sakana AI, ICLR 2026)
measures Japanese accounting-fraud detection from annual reports (有価証券報告書).

| Task | Best published LLM | Baseline |
|---|---|---|
| Accounting fraud detection (ROC-AUC / MCC) | 0.73 / 0.32 — Claude 3.5 Sonnet with narrative text | Logistic regression 0.68 / 0.17 |

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

- **Local inference only.** No paid model APIs, no spend.
- **No manual classification.** Nothing in the plan may depend on a human reading and
  labelling documents by hand.
- Roughly 2–3 hours per week, single contributor.

## What is and is not claimed

**Not claimed: the published 0.73.** That figure is Claude 3.5 Sonnet. An open-weight
model scoring differently measures the model, not the benchmark. This project does not
reproduce or contest it.

**Claimed instead:** the first open-weight evaluation of EDINET-Bench with
company-clustered intervals, reproducible by anyone with no API budget. Mechanism
questions — how much of a score is era detection, whether prompting in Japanese changes
the result — remain fully answerable locally, because they ask whether a factor *moves*
the number rather than how capable a given model is.

**Standing caveat.** EDINET-Bench is roughly 49% fraud; the real-world rate is a small
fraction of one percent. At a true rate near 1 in 200, a model catching 70% of frauds and
clearing 70% of clean companies yields about 3,020 alerts of which roughly 35 are real.
Any score here is a research claim, not a product claim.

---

## Measured feasibility

*M5 Max, 128 GB, `qwen3.5-122b-ctx` at 131,072 context.*

| Input | chars | tokens (0.79 tok/char) |
|---|---:|---:|
| `text` p50 | 34,543 | ~27,100 |
| `text` max | 78,129 | ~62,000 |
| `summary`+`bs`+`pl`+`cf` | ~9,200 | ~7,300 |

Every filing fits in context with ~2× headroom. **Truncation is not required and must not
be introduced silently.**

| Throughput | |
|---|---|
| Prefill | 782 tok/s |
| Generation | 49 tok/s |
| Per item, full text | ~40–60 s |

| Run | Items | Estimate |
|---|---:|---|
| Dev subset, structured fields | 50 | ~8 min |
| Test split, full text | 224 | ~3 h |
| Full dataset, full text | 1,089 | ~15 h — one overnight run |

**Hazard:** `qwen3.5-122b` is a reasoning model. On a 64-token output budget it consumed
the entire budget thinking and returned an empty response. The harness must budget for
thinking tokens or suppress them. Hit mid-sweep, this produces a night of blank verdicts.

---

## The harness

**Three run modes.** `record` calls the model and writes events; `replay` re-derives
predictions and metrics from a prior run's recorded responses with no model calls;
`rescore` replays with new parsing or metric code against the same fixed responses.

**Replay means replaying recorded responses, not regenerating them.** Model calls are not
deterministic even at fixed settings. That distinction is the point: it separates *did my
scoring logic change?* from *did the model change?* Pinned open weights make the second
question tractable too — the model is a file with a digest, not a service that shifts
underneath you.

**The event log** is append-only SQLite. One step per item today; the schema carries N
steps so the agent phase needs no migration. Prompts and responses live in a
content-addressed blob table keyed by SHA-256, which keeps the database small and makes
"did the prompt change?" a hash comparison rather than a diff.

**The prediction contract** is structured output, parsed strictly. Parsing raises; the
runner records `item_failed`; scoring refuses to compute metrics over a run with
unacknowledged failures. Silent drops are a quiet bias — if parsing fails more often on
harder filings, the reported score covers an easier subset than the one advertised.

**Metrics.** ROC-AUC and MCC are trivial; the error bars are the deliverable. The test
split is 224 items and published MCC is 0.32 — at that n, an apparent improvement to 0.38
is indistinguishable from noise. Use a paired bootstrap when comparing two systems on the
same items, and **always resample companies, not filings** (see
[02](./02-what-the-dataset-contains.md) §3).

---

## Workstreams

| | | Needs |
|---|---|---|
| A | **Classical forensic-accounting features** — Beneish M-Score, Dechow F-Score, Benford's Law, accruals — over `bs`/`pl`/`cf`. Not previously run on this benchmark. Must control for filing era, since a feature set encoding era will look better than it is. | No model calls |
| B | **Open-weight baseline** on dev and test splits, company-clustered intervals | Local inference |
| C | **Era ablation** — how much of a text-based score is recoverable from era cues alone | Local inference |
| D | **Japanese-prompt experiment** — the published eval prompt is English over a Japanese source | Local inference |
| E | **The agent** — multi-step investigation, temporal diffing, cross-source corroboration | Local inference |
| F | **Event-sourced replay and per-run accounting** | Harness only |

## Open questions

- What is the real base rate of fraud-corrected annual reports among Japanese listed
  companies? Computable from the local metadata archive.
- Do parse failures correlate with filing year, company size, or accounting standard?
  (~20% were dropped during dataset construction.)
- Can an out-of-time split have a positive class at all, given the right-censoring in
  [02](./02-what-the-dataset-contains.md) §2?

## Sources

- **EDINET-Bench** — Sugiura, Ishida, Makino, Tazuke, Nakagawa, Nakago, Ha. Sakana AI, ICLR 2026.
- **Herculean** — agentic finance benchmark, arXiv 2605.14355, May 2026.
- **EDINET API specification** — ESE140206.pdf, for the ten-year retention rule.
