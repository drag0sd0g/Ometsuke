# How EDINET-Bench's Fraud Labels Were Made

**Why this document exists:** every score this project reports is bounded by the quality of EDINET-Bench's labels. Before optimising against a number, it is worth knowing exactly what that number measures.

---

## 1. What the benchmark is

EDINET-Bench is a Japanese financial benchmark published by Sakana AI (ICLR 2026). It contains three tasks; we care about **accounting fraud detection**.

The task: given a Japanese annual report (有価証券報告書), decide whether it is fraudulent.

| | Count |
|---|---|
| Source corpus | ~41,691 reports, April 2014 – April 2025 |
| Labelled before parsing | 668 fraud / 700 non-fraud |
| Final dataset after parse failures | 534 fraud / 555 non-fraud = **1,089** |
| Train split | 865 |
| Test split | **224** (122 fraud, 102 non-fraud) |

Published baselines on the test split:

| System | ROC-AUC | MCC |
|---|---|---|
| Claude 3.5 Sonnet (with narrative text) | 0.73 | 0.32 |
| Logistic regression on summary indicators | 0.68 | 0.17 |

No confidence intervals are reported anywhere.

---

## 2. How a filing gets labelled "fraud"

This is the core of it. The pipeline is three scripts in `SakanaAI/edinet2dataset`, run in order.

### Step 1 — collect amendments (`prepare_fraud.py`)

Japanese companies that need to correct a filed annual report submit a **訂正有価証券報告書** (amended annual report). Sakana downloaded **6,712** of these covering ten years, and extracted the text with `pdfminer`.

### Step 2 — ask an LLM whether the amendment smells like fraud

Each amendment's **提出理由** (reason for submission) section is passed to **`claude-3-7-sonnet-20250219`** at temperature 0. The prompt asks it to look for indicators such as:

- 不適切会計 — improper accounting
- 粉飾決算 — window dressing / falsified accounts

and to distinguish substantial accounting problems from a simple clerical fix. Output is JSON: a boolean, an explanation, and the company name.

> Note a discrepancy worth recording: the arXiv text refers to Claude 3.5 Sonnet for labelling, while the shipped code calls `claude-3-7-sonnet-20250219`. The code is authoritative for what actually produced the released dataset.

### Step 3 — walk back from the amendment to the original filing

An amendment declares which document it corrects, via the XBRL element `IdentificationOfDocumentSubjectToAmendmentDEI`. The code reads that field to recover the **original** filing's document ID, then downloads that original.

**This is the key design decision, and it's a good one.** The fraud label is attached to the *original, pre-correction* filing — not to the amendment. So the model is shown the filing as it was originally published, before anyone knew it was wrong, and asked to spot the problem. That is the honest version of the task.

### Step 4 — build the negative class (`prepare_nonfraud.py`)

Negatives are constructed by a different procedure entirely:

1. Collect the EDINET codes of every company in the fraud set.
2. Randomly sample company directories (`random.seed(42)`).
3. Keep a company only if its EDINET code appears **nowhere** in the fraud set.
4. From each kept company, pick **one filing at random**.

### Step 5 — split (`prepare_dataset.py`)

`train_test_split(test_size=0.2, random_state=42)`, applied **to the list of unique EDINET codes**, not to individual records. Every filing from a given company lands entirely in train or entirely in test — so no company appears on both sides. Records that fail TSV parsing, or that lack an EDINET code, are dropped.

---

## 3. What the label actually means

Stripping away the machinery, a positive label means:

> *This filing was later corrected by an amendment whose stated reason an LLM judged to describe a serious accounting problem.*

And a negative label means:

> *This company never filed any amendment that the LLM flagged, at any point in a ten-year window.*

Neither is "fraud" in an adjudicated, legal sense. They are proxies. Reasonable proxies — but proxies, and the gap between proxy and reality is where the problems below live.

---

## 4. Six problems, ranked by how much they matter

### 4.1 The class balance is nothing like reality — **highest impact**

The dataset is roughly 49% fraud. In the real world, the share of annual reports later corrected for accounting fraud is a small fraction of one percent.

Why this matters, in plain terms: **a good score here does not imply a usable screening tool.** Suppose a model gets 70% of frauds right and correctly clears 70% of clean companies, and suppose the true rate is around 1 in 200 filings. Out of 10,000 filings:

- 50 are fraudulent → the model catches ~35
- 9,950 are clean → the model wrongly flags ~2,985

So of roughly 3,020 alerts, about **35 are real — barely 1%**. That is arithmetic, not pessimism, and no amount of benchmark improvement changes the shape of it.

This isn't a flaw in the benchmark. A balanced set is a perfectly legitimate *measuring instrument* — it's how you compare models cleanly. But it means any score we report is a **research claim, not a product claim**, and we should say so plainly and unprompted. Anyone senior will spot it immediately, and saying it first is worth a great deal.

### 4.2 The labels come from an LLM, and its errors are inherited

The paper is candid about three failure modes:

- **Honest mistakes counted as fraud.** The prompt doesn't reliably separate intentional falsification from an unintentional misstatement.
- **Hallucination.** An LLM classifier can simply be wrong.
- **Irrelevant corrections swept in.** Manual spot-checks found amendments about things like the number of board members — nothing to do with the financial statements.

Effect: some unknown fraction of the positive class isn't fraud. That **caps the achievable score** — if 15% of positives are mislabelled, no model can exceed the ceiling that noise imposes, and every reported figure is measured against a partly-wrong answer key.

**We do not currently know what that fraction is. Nobody has measured it.** See §6.

### 4.3 The negative class is cleaner than reality

Two things are going on.

First, the one the paper admits: **undiscovered fraud is sitting in the negative class**. Fraud that was never caught looks exactly like innocence.

Second, one it doesn't dwell on: negatives exclude **every filing from any company that was ever caught**. So the negative class is drawn purely from never-caught companies. Reality doesn't sort itself that neatly — a real screening system sees clean years from dirty companies all the time, and those are precisely the hard cases. Their absence makes the task easier than the real thing.

There's also a subtler asymmetry: **positives are a specific, targeted filing** (the one that got corrected), while **negatives are one random filing** from a clean company. If those two selection processes favour different years or company sizes, the model can pick up on that difference instead of on fraud.

### 4.4 The split is random, not temporal — so contamination is unaddressed

The split is by company, with `random_state=42`. Train and test both span 2014–2025.

Company-level grouping is the right call — it stops the model memorising a company rather than learning the signal. But it does nothing about the other problem: **these filings are public documents that were very likely in the models' pretraining data**, and so were the news reports of the resulting scandals. A model may "know" that a particular company was caught, without reading anything in the filing at all.

The paper names this risk and notes the pipeline can be re-run on newer filings. Nobody has done it.

**This is the direct justification for Ometsuke's Phase 2**: build a held-out split from filings published after the models' training cutoffs. It settles the question rather than arguing about it, and it's a contribution in its own right.

### 4.5 About 20% of labelled data was dropped, and probably not at random

1,368 labelled records became 1,089 — roughly a fifth lost to TSV/PDF parsing failures.

If parse failure correlates with anything real — older filings, unusual accounting standards, smaller companies with different filing software — then the surviving sample is skewed, and the benchmark quietly measures performance on the subset that happened to parse.

The prompt partially acknowledges this: it warns the model that missing values appear as `-` and shouldn't be read as suspicious. That mitigates the model treating gaps as evidence, but does nothing about the selection bias in what survived.

### 4.6 One fraud can produce several labelled filings

Real accounting fraud usually spans multiple years, and a company typically files one amendment per affected year. Each of those amendments points back to its own original filing, so **one scandal can contribute several positive records**.

Company-level splitting prevents this from leaking across train and test. But it does mean the fraud class may be concentrated in fewer distinct companies than the raw count of 534 suggests, so the effective sample size is smaller than it looks — which makes §5's point about error bars worse, not better.

---

## 5. Why error bars are non-negotiable here

The test set is 224 items. Published MCC is 0.32.

With a sample that small, if you'd happened to draw a different 224 companies you'd get a visibly different number. The spread is likely on the order of ±0.1 or more. **So an "improvement" from 0.32 to 0.38 could easily be pure luck**, and reporting it as progress would be wrong.

Sakana's `make_leaderboard.py` computes accuracy, precision, recall, F1, MCC and ROC-AUC — all as **point estimates only, formatted to two decimal places**. No intervals, no significance tests.

This is straightforwardly an unoccupied contribution: **nobody has published an error bar on this benchmark.** Adding one is a few hours of work and it's the difference between a leaderboard entry and a result.

Concretely, we want a **paired bootstrap**: because two systems are scored on the same 224 items, comparing them pairwise gives much more statistical power than comparing two independent intervals.

---

## 6. What we take forward

| Finding | Consequence for Ometsuke |
|---|---|
| Labels are LLM-derived proxies with admitted noise | Audit them before trusting any score (§6) |
| 49/51 balance vs. sub-1% reality | State the research-not-product framing openly, always |
| Random split, public documents, contamination unaddressed | Phase 2 out-of-time split is a real contribution |
| No confidence intervals anywhere | Phase 1 adds them; use paired bootstrap |
| Label attaches to the pre-correction original | The task framing is sound — build on it |
| ~20% dropped to parse failures | Check whether losses are systematic |

---

## 7. Open questions

Things we don't know yet and should:

- What *is* the real base rate of fraud-corrected annual reports among Japanese listed companies? The 1-in-200 figure above is an assumption used for illustration, not a measured number.
- How many distinct companies are behind the 534 positive records? (Determines effective sample size.)
- Do parse failures correlate with filing year, company size, or accounting standard?
- Does the prompt's framing — "the numbers were verified by a CPA, look for non-numerical red flags" — help or hurt? It's an odd instruction given that the labels come from filings whose numbers were exactly what got corrected.
- Does prompting in Japanese rather than English change the result? Sakana's prompt is English over a Japanese source document.

---

## Sources

- Paper: [EDINET-Bench (arXiv 2506.08762)](https://arxiv.org/html/2506.08762v1), ICLR 2026
- Eval code: [SakanaAI/EDINET-Bench](https://github.com/SakanaAI/EDINET-Bench) — `src/edinet_bench/predict.py`, `make_leaderboard.py`, `prompt/fraud_detection.yaml`
- Dataset construction: [SakanaAI/edinet2dataset](https://github.com/SakanaAI/edinet2dataset) — `scripts/fraud_detection/prepare_fraud.py`, `prepare_nonfraud.py`, `prepare_dataset.py`
- Dataset: [SakanaAI/EDINET-Bench on Hugging Face](https://huggingface.co/datasets/SakanaAI/EDINET-Bench)
