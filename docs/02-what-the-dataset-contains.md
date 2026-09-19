# What the Released Dataset Actually Contains

**Depends on:** [01 — How EDINET-Bench's Fraud Labels Were Made](./01-how-edinet-bench-labels-were-made.md)
**Why this document exists:** every number this project reports is bounded by what the benchmark actually ships. Checking the released files directly, rather than trusting the paper, turned up four things that change how any score on it must be measured.

---

## 1. The findings

1. **The released dataset does not say which amendment produced any fraud label.** The field that should carry it is empty for 531 of the 534 positives, and the cause looks like a join bug in Sakana's dataset-assembly script. The mapping has to be reconstructed from EDINET.
2. **The positive class is systematically older than the negative class**, by construction. Ranking the test split on filing date alone — no financial data, no text — gives **ROC-AUC 0.635**, against published baselines of 0.68 (logistic regression) and 0.73 (Claude 3.5 Sonnet with narrative text).
3. **The 534 positives come from 200 distinct companies**, and the 122 positives in the test split come from **50**. Every confidence interval on this benchmark has to be clustered by company, or it is too narrow.
4. **Explicit misconduct vocabulary appears in only 35% of the amendment texts**, and the obvious words for a clerical correction — 誤記, 誤植 — appear in none of them.

---

## 2. The amendment link is missing

### What shipped

The parquet has twelve columns, not the ten recorded in `docs/01`:

```
meta  summary  bs  pl  cf  text  label  explanation  edinet_code  ammended_doc_id  doc_id  file_path
```

`ammended_doc_id` (the misspelling is theirs) should hold the document ID of the 訂正有価証券報告書 whose 提出理由 the labeller read. `explanation` should hold the labeller's own reasoning.

Querying both splits directly:

| | positives (534) | negatives (555) |
|---|---|---|
| `ammended_doc_id` non-empty | **3** | 0 |
| `explanation` non-empty | **3** | 0 |

And in all three surviving rows, `ammended_doc_id == doc_id` — which cannot be a real amendment/original pair, since they are by definition different documents.

### Why

In `SakanaAI/edinet2dataset`, `scripts/fraud_detection/prepare_dataset.py`:

- `load_fraud_explanation()` builds its lookup table keyed by `analysis["amended_doc_id"]` — the **amendment's** ID (line 29).
- `build_data_entry()` looks the row up by `os.path.basename(tsv_path)` — the **original filing's** ID, because the TSVs on disk are the originals that were downloaded for the dataset (lines 46–48).

The two key spaces don't overlap, so the join misses everywhere. It should key on `original_doc_id`, which the analysis records already carry.

That also explains the three survivors: they are filings whose "original" is itself an amendment attachment (their `提出書類` reads 有価証券報告書（…訂正報告書の添付インラインXBRL）), so their `doc_id` collides with an amendment ID in the table and matches by accident. A coincidental key collision is exactly what this diagnosis predicts, which is the best confirmation available without re-running their pipeline.

One further detail: the published column is `ammended_doc_id` while the repository's current code writes `amended_doc_id`. The released artifact was built by a slightly different version of the script than the one on `main`. The empty field is the operative fact either way.

### Consequence

Sakana's intermediate `analysis/result.jsonl` — which does hold `amended_doc_id`, `original_doc_id` and `explanation` per record — was never published. From the released dataset alone it is **not possible** to find the text that justified any given fraud label. That mapping has to be rebuilt from EDINET directly.

*This is also a small contribution in its own right: a reproducible defect report against a published ICLR benchmark, with a one-line fix.*

---

## 3. Rebuilding the mapping — and the clock on it

### The route

EDINET's document-list API is queryable by submission date only, so:

1. Sweep `documents.json` (`type=2`) day by day across the retrievable window, archiving every record.
2. Keep annual amendments — `ordinanceCode 010`, `formCode 030001` — and read their `parentDocID`, which points at the document being corrected.
3. Match `parentDocID` against our 534 `doc_id`s.
4. Download the matched amendments and extract the 提出理由.

`parentDocID` is present and populated: a spot check on 2021-06-30 returned 19 annual amendments, e.g. `S100LVBT` (ＯＵＧホールディングス) → parent `S100GB3Q`.

**Verification requirement.** Sakana did not use `parentDocID`; they read the XBRL element `IdentificationOfDocumentSubjectToAmendmentDEI` out of each amendment's TSV. Before trusting the bulk map, a subsample must be checked against that element and required to agree **100%**. If `parentDocID` is unreliable for older filings, the failure mode is silent: we would match fewer than we should and read it as data loss rather than as a bug.

### The clock

EDINET deletes documents ten years after submission. The API spec (ESE140206.pdf) states 「既に 10 年を経過した書類については取得できません」, and the boundary is exact — on 2026-08-23, a request for 2016-08-22 returns data and 2016-08-21 returns 404.

The positive class is concentrated in the early years (77 filings with fiscal years ending in 2015, 72 in 2016), and their amendments were filed one to three years after the original. Some are already unrecoverable, and the wall advances one day per day.

**So the archive is the deliverable, not a means to it.** The metadata sweep is being kept in `data/edinet-metadata/` and the amendment documents will be kept alongside it. Nothing about this gets easier by waiting.

**Retention decision, 2026-09-19: the archive is deliberately not backed up.** It is
gitignored (305 MB) and exists on local disk only. The consequence is accepted and
recorded here rather than left implicit: the portion of the archive that has passed the
ten-year wall **cannot be rebuilt at any price** if `data/` is lost. Re-running the sweep
would recover only what EDINET still serves, which shrinks by one day per day.

### What it recovered (run 2026-08-23)

The sweep took 3,654 days — 2016-08-22 to 2026-08-23 — and returned **891,724 records** with no gaps and no count mismatches against the API's own totals. Among them, **6,503 annual amendments**, against the 6,712 Sakana processed over a window shifted two years earlier. Earliest archived amendment: 2016-09-02.

Matching `parentDocID` against the 534 positives:

| | |
|---|---|
| Positives whose amendment is recoverable | **396 / 534 (74.2%)** |
| Amendment rows (some filings were amended more than once) | 559 |
| Unmatched, no archived amendment covers that fiscal period | 137 |
| Unmatched, unexplained | **1** |

The single unexplained case is `S100DNCW`, one of the three anomalous rows from §2 — a "filing" that is itself an amendment, so its parent is another amendment rather than the annual report. Not a mapping error.

**The loss is entirely the retention wall, and it is sharply year-shaped:**

| Fiscal year | Recovered / total |
|---|---|
| 2015 | **0 / 77** |
| 2016 | 14 / 72 |
| 2017 onwards | 382 / 385 (99.2%) |

Multi-year restatements explain the shape: a fraud discovered in 2016 produces amendments for several prior years on the same day, so one pre-wall filing date takes out a whole run of fiscal years.

**Consequence.** Any analysis resting on recovered amendments covers 396 positives, not 534, and contains **no FY2015 filings at all**. That restriction and the missing 26% must be stated wherever such a figure is reported. Whether label quality differs in the lost years is not knowable and should not be guessed at.

### Verification (known-answer check, passed)

`parentDocID` is EDINET's metadata; Sakana used the XBRL element instead. Sampling 15 amendments and extracting `IdentificationOfDocumentSubjectToAmendmentDEI` from each: **15 agreements, 0 disagreements, 0 missing** (`scripts/verify_parent_links.py`, seed 20260823).

Worth recording how that check behaved the first time it ran: it reported PASS having extracted the element from **zero** of the 15 files. The element ids carry a taxonomy namespace (`jpdei_cor:…`) and every field is quoted, so matching the bare name against the start of the line found nothing — and the verdict only tested for disagreements, of which there were none, because there were no comparisons at all. A check that cannot fail is worse than no check, because it produces a green light. The fix requires `agree == n` with no absences.

---

## 4. Filing date alone gets ROC-AUC 0.635

### The distribution

Positives are older than negatives, and the gap is not subtle:

| Fiscal year end | Positives | Negatives |
|---|---|---|
| 2015 | 77 | 63 |
| 2016 | 72 | 57 |
| 2017 | 76 | 54 |
| 2018 | 65 | 47 |
| 2019 | 59 | 48 |
| 2020 | 50 | 49 |
| 2021 | 49 | 64 |
| 2022 | 44 | 54 |
| 2023 | 28 | 55 |
| 2024 | 14 | 63 |
| 2025 | 0 | 1 |

Mean fiscal-year end, test split: **2018.15** for positives, **2019.59** for negatives. Train split: 2018.58 against 2019.53.

### Why it happens

Right-censoring. A filing becomes a positive only once someone discovers the problem and the company files an amendment, which takes years. A 2024 annual report whose fraud has not yet surfaced is, at corpus-build time, indistinguishable from a clean one — and the negative class was sampled uniformly across the whole window. So recency correlates with innocence as an artifact of when the dataset was built.

### What it is worth

Score each test item by nothing but "older filing ⇒ more likely fraud", using `meta.当事業年度終了日` and no other input:

**ROC-AUC 0.635** on the 224-item test split, 95% bootstrap CI **[0.549, 0.719]** (2,000 resamples of *companies*, seed 42). On the train split, 0.591.

Published baselines: **0.68** logistic regression on summary indicators, **0.73** Claude 3.5 Sonnet with narrative text.

### What this does and does not mean

**It does mean** a substantial share of the benchmark's discriminative signal is available from a date, and that any system reading era cues gets that share for free. It is a property of the dataset, independent of any model.

**It does not mean** the published systems achieved their scores this way. Sakana's `predict.py` defaults to `--sheets summary bs pl cf`; `meta` is not passed, so the date is not handed over directly. But the 0.73 figure is the run that adds `text`, and the narrative sections are dense with absolute dates and 平成/令和 era names, so era is recoverable by any model that looks for it. Whether it does is a separate, testable question.

**It is not established** that this is unreported. Sakana's repo contains `contamination/analyze_performance_per_year.py`, which slices *performance by* year as a contamination check — a different quantity from a year-only baseline. We have not read the paper body looking for one.

### The experiment this suggests

A date-ablation: run the same model twice, once on the filing as-is and once with dates and era names redacted from `text`, and report the gap. That measures how much of the score is era detection. It is cheap, it is one variable, and it slots naturally beside the Japanese-prompt experiment already queued in §15.

### And the problem it creates for Phase 2

Phase 2 is an out-of-time split from filings published after the models' training cutoffs. The censoring above is exactly what makes that hard: filings recent enough to be uncontaminated are also too recent for their frauds to have been discovered, so a fresh split will be almost all negatives. The two constraints pull in opposite directions. This needs a design answer before Phase 2 starts — most likely a longer lag plus explicit acceptance of a small positive class, sized in advance rather than discovered late.

---

## 5. 534 positives, 200 companies

| Filings from one company | Companies |
|---|---|
| 1 | 64 |
| 2 | 41 |
| 3 | 34 |
| 4 | 30 |
| 5 | 22 |
| 6 | 7 |
| 7 | 2 |

In the **test split**: 122 positive filings from **50 companies**; 102 negatives from 102 companies.

This answers an open question from `docs/01` §8, and it has two consequences.

**For Phase 1 metrics.** The bootstrap must resample **companies, not filings**. Filings from one company describe one scandal in near-identical language; treating them as independent draws makes every interval too narrow. This is the kind of error that produces a confident, wrong number and looks fine, so it needs a behavioural check rather than a code read. The check is that a company-clustered interval must come out *wider* than a naive one on the same data.

The same applies to sampling: a simple random sample of 50 filings is not 50 independent observations — it is closer to 35–40.

Also worth recording: 4 of the 534 positives are not plain 有価証券報告書. Their `提出書類` field reads 有価証券報告書（…訂正報告書の添付インラインXBRL） or has trailing whitespace — the same anomaly that produced the three accidental joins in §2.

---

## 6. What the amendment texts contain

574 提出理由 were extracted from the recovered amendments. Document frequency across all
574, for the terms that carry the meaning:

| term | docs | | term | docs |
|---|---|---|---|---|
| 財務諸表 / 連結財務諸表 | 71% | | 不適切な会計処理 | 25% |
| 監査法人 | 70% | | 誤り | 24% |
| 計上 | 51% | | 特別調査委員会 | 23% |
| 過年度 | 47% | | 社内調査 | 15% |
| 監査報告書 | 44% | | 不正 | 15% |
| 調査委員会 | 41% | | 第三者委員会 | 14% |
| 売上 | 31% | | 架空 | 11% |
| | | | 減損 / 引当金 | 10% |

Two things in that table are worth stating outright, because both contradict what a
reasonable prior would suggest.

**誤記 and 誤植 — the obvious words for a clerical correction — appear in 0 of 574 texts.**
The word doing that work in this corpus is **誤り** (137 texts, 24%). Any keyword scheme
built on the obvious pair matches nothing at all.

**Explicit misconduct vocabulary is a minority.** Only **202 of 574 (35%)** contain
不適切な会計処理 / 粉飾 / 会計不正 / 不正 anywhere. Whatever signal separates a
financial-statement correction from an unrelated one, in 65% of cases it is not a
misconduct keyword.

---

## 7. How to reproduce these numbers

No API key needed for §2, §4 and §5 — all three come from the released parquet:

```
https://huggingface.co/datasets/SakanaAI/EDINET-Bench/resolve/refs%2Fconvert%2Fparquet/fraud_detection/{train,test}/0000.parquet
```

- **Column emptiness (§2):** count rows where `ammended_doc_id <> ''`, grouped by `label`.
- **Year distribution and AUC (§4):** `json_extract_string(meta, '$.当事業年度終了日')`; score = negative days since 2015-01-01; AUC by rank comparison with ties at 0.5; CI by resampling `edinet_code` groups with replacement, 2,000 draws, seed 42.
- **Company counts (§5):** `count(DISTINCT edinet_code)` by label and split.

The retention boundary in §3 was found by binary search over 2016 against the live API and is reproducible only until it moves.

---

## 8. Still open

- ~~Does `parentDocID` agree with `IdentificationOfDocumentSubjectToAmendmentDEI`?~~ **Answered: 15/15 on the verification sample** (§3).
- ~~What share of the 534 amendments survives the ten-year wall?~~ **Answered: 396 (74.2%), and the loss is entirely FY2015–2016** (§3).
- Does the paper body report a date-only or metadata-only baseline?
- How much of the 0.73 is era detection? Answered by the date-ablation in §4.
- **57 negative-labelled filings were themselves later amended** (62 amendments; `data/negative-hits.csv`). Seven of those amendments were filed after April 2025 and so were invisible to Sakana; the other 55 are amendments their labeller saw and declined to flag, since any company it *had* flagged was excluded from the negative class by construction. They are the only measurable surface on negative-class error, and at 57 items the set is small enough to process exhaustively with no sampling.
