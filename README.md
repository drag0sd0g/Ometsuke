# Ometsuke

[![CI](https://github.com/drag0sd0g/Ometsuke/actions/workflows/ci.yml/badge.svg)](https://github.com/drag0sd0g/Ometsuke/actions/workflows/ci.yml)

<img width="657" height="847" alt="ometsuke" src="https://github.com/user-attachments/assets/fa872a02-86c7-4eeb-bcf9-37669a963af1" />

**大目付** — the senior inspectorate of the Edo period.

An evaluation harness for Japanese accounting-fraud detection, built on
[EDINET-Bench](https://huggingface.co/datasets/SakanaAI/EDINET-Bench) (Sakana AI, ICLR 2026),
whose output is a number you can re-derive months later rather than one you have to trust.

**Everything runs on open weights, locally.** No paid model APIs are used and none are
needed to reproduce any result here. See [the charter](docs/00-project-charter.md) for
what that constraint costs and what it buys.

Work in progress. Below is what has been established so far.

---

## Findings

**The released dataset cannot tell you why any filing was labelled fraud.**
Each fraud label comes from an LLM reading the 提出理由 of an amendment, but the column
linking a filing to that amendment — `ammended_doc_id` — is **empty for 531 of the 534
positives**, along with `explanation`. The cause is a join-key mismatch in
`edinet2dataset/scripts/fraud_detection/prepare_dataset.py`: the lookup table is keyed
by the amendment's id, and looked up by the original filing's. The evidence for every
positive label is therefore absent from the published artifact.

**Filing date alone scores ROC-AUC 0.635.**
Positives are systematically older than negatives — mean fiscal year end 2018.2 against
2019.6 on the test split — because a filing only becomes a positive once its fraud has
been discovered and amended, which takes years. Ranking the test split on
`当事業年度終了日` and nothing else gives **0.635** (95% company-clustered CI
[0.549, 0.719]), against published baselines of 0.68 for logistic regression and 0.73
for Claude 3.5 Sonnet with narrative text.

**534 positives come from 200 companies; the 122 test positives from 50.**
Filings from one company describe one scandal in near-identical language. Any confidence
interval on this benchmark that resamples filings rather than companies is too narrow.

**Misconduct vocabulary is a minority of the evidence.** Across 574 amendment texts
recovered from EDINET, only **35%** contain 不適切な会計処理 / 粉飾 / 会計不正 / 不正
anywhere — and 誤記 / 誤植, the obvious words for a clerical correction, appear in
**none of them**.

→ [docs/02](docs/02-what-the-dataset-contains.md), with reproduction steps

---

## What's here

| | |
|---|---|
| [`docs/00`](docs/00-project-charter.md) | the charter — what the project claims, what it refuses to claim, and the constraints that fix its scope |
| [`docs/01`](docs/01-how-edinet-bench-labels-were-made.md) | how EDINET-Bench's fraud labels were built, verified against the shipped code |
| [`docs/02`](docs/02-what-the-dataset-contains.md) | the findings above, with reproduction steps |
| `scripts/` | reconstruction of the amendment → filing mapping the dataset omits: a ten-year sweep of EDINET's document API, verified against the XBRL element Sakana used (15/15 agreement), recovering **396 of 534** positives — the rest lost to EDINET's ten-year deletion policy |
| `src/ometsuke/` | the harness: an append-only SQLite event log, content-addressed prompts and responses, `record` / `replay` / `rescore`, metrics with company-clustered bootstrap intervals |

## The harness

Model calls are not deterministic even at fixed settings, so **replay means replaying
recorded responses, not regenerating them**. That is what makes it useful: it separates
*did my scoring logic change?* from *did the model change?* Pinned open weights make the
second question tractable too — the model is a file with a digest, not a service that
shifts underneath you.

Correctness is asserted behaviourally rather than by inspection. Among the tests: a
perfect classifier must score AUC exactly 1.0; random scores must produce an interval
covering 0.5; shuffled labels must give MCC ≈ 0; a company-clustered interval must come
out **wider** than the naive one on the same data; replay must make zero model calls and
be byte-identical across repetitions; and a malformed response must raise rather than be
silently dropped, since silent drops score an easier subset than the one advertised.

```bash
uv run ometsuke run --split dev --model stub   # record
uv run ometsuke replay <run_id>                # re-derive, no model calls
uv run ometsuke score <run_id> --split dev     # AUC and MCC, clustered intervals
uv run pytest
```

## Scope

**The published 0.73 is not reproduced here, and cannot be.** That figure is Claude 3.5
Sonnet; an open-weight model scoring differently measures the model, not the benchmark.
What this offers instead is an open-weight evaluation of EDINET-Bench with
company-clustered intervals, reproducible by anyone with no API budget.

EDINET-Bench is roughly 49% fraud; the real-world rate is a small fraction of one
percent. At a true rate near 1 in 200, a model catching 70% of frauds and clearing 70%
of clean companies produces about 3,020 alerts of which roughly 35 are real — about 1%
precision. A balanced benchmark is a legitimate measuring instrument, but **any score
reported here is a research claim, not a product claim.**
