# Conclusion

**What EDINET-Bench's labels turned out to be recoverable from, and what they did not.**

Seven configurations were evaluated on a local open-weight model, every interval
resampled by company, every run event-sourced and replayable. Six of the seven returned a
null. The one that did not, did not survive the held-out split.

**The finding is negative, and it replicates across methods:** on this benchmark, a
single filing's disclosure does not appear to carry recoverable signal about whether that
filing was later corrected for accounting misconduct.

---

## 1. Everything that was tried

| | what changed | effect on ranking (ROC-AUC) |
|---|---|---|
| [05](./05-open-weight-baseline.md) §3 | auditor framing removed | −0.004 [−0.037, +0.028] |
| [05](./05-open-weight-baseline.md) §4 | score scale — 3 distinct values → 9 | −0.008 [−0.038, +0.024] |
| [05](./05-open-weight-baseline.md) | instruction language (Japanese, dev only) | worse on every axis |
| [06](./06-narrative-sections.md) §2 | input: narrative vs statements — **train** | +0.086 [+0.033, +0.137] |
| [06](./06-narrative-sections.md) §2a | the same, on the **held-out split** | **−0.004 [−0.111, +0.100]** |
| [06](./06-narrative-sections.md) §3a | prior year added, no instruction | +0.001 [−0.039, +0.040] |
| [06](./06-narrative-sections.md) §3a | instruction to compare years | −0.035 [−0.074, +0.004] |
| [03](./03-forensic-accounting-features.md) | Beneish M-score (no model at all) | **0.438** — below chance |

Against a date-only control of **0.594** [0.548, 0.640], and a best open-weight score of
**0.550** [0.515, 0.582] on the structured sheets.

**Four tight nulls on prompting. One apparent effect on input that vanished on held-out
data. One classical screen below chance.**

---

## 2. What that means

**The model beats chance and not the calendar.** 0.550 clears 0.5 with the interval
excluding it, so there is *some* signal. But the paired comparison against filing date
alone is −0.044 [−0.105, +0.016] — indistinguishable. A 122B model reading a Japanese
annual report ranks filings no better than sorting them by 当事業年度終了日.

**Prompting is not the lever.** Three variables, three full sweeps of 865 filings, three
intervals that straddle zero and are narrow enough to say so. The auditor framing moves
calibration enormously — 338 filings change class — while leaving ranking untouched.
Forcing a graded score tripled the distinct values and changed nothing.

**Temporal context is not the lever either.** The cheapest form of this project's central
hypothesis — show the model last year's risk and segment disclosures — is flat at +0.001
with a tight interval. The instruction to *compare* costs 0.035, consistently across two
comparisons: directing attention toward change pulls it away from whatever was working.

**Input looked like the lever, and then did not.** Narrative sections beat the financial
statements by +0.086 on train, interval excluding zero — the only positive result in the
project. On the held-out split the same comparison came back −0.004. Held back from the
start, spent once, on a configuration fixed before the decomposition ran.

---

## 3. Why the benchmark makes this hard

Five structural properties were measured, each documented with reproduction steps. Any one
of them will produce a confident, meaningless number if missed.

| | finding |
|---|---|
| [02](./02-what-the-dataset-contains.md) §2 | **The labels are severed from their evidence.** `ammended_doc_id` is empty for 531 of 534 positives — a join-key mismatch in the published `prepare_dataset.py`. One-line fix. |
| [02](./02-what-the-dataset-contains.md) §4 | **Filing date alone scores 0.635.** Positives are older by construction: a filing becomes positive only once its fraud is found, which takes years. |
| [02](./02-what-the-dataset-contains.md) §5 | **534 positives come from 200 companies.** Any interval resampling filings rather than companies is too narrow. |
| [02](./02-what-the-dataset-contains.md) §5 | **Having a second filing *is* the label.** All 105 multi-filing training companies are positive; all 253 consecutive-year pairs end in fraud. Any use of a company's other filings reads the answer key. |
| [02](./02-what-the-dataset-contains.md) §5 | **The ten-year wall biases every multi-year analysis**, and the held-out split too: 48 of 224 test filings are unreachable, at 64.6% fraud against 51.7% among the survivors. |

A benchmark whose strongest single recoverable feature is the filing date, and where
having more than one filing determines the label, is measuring something other than what
it appears to.

---

## 4. What this does not claim

**Not that the published 0.73 is wrong.** That is Claude 3.5 Sonnet with narrative text;
nothing here calls a frontier model. No comparison was made and none should be inferred.

**Not that fraud is undetectable from Japanese disclosure.** Only that *these* labels, on
*this* benchmark, resisted every method tried: eight classical ratios, three prompt
variables, two input types, and one year of temporal context.

**Not that agentic investigation would fail.** The cheapest component of it — one prior
year, one comparison prompt — is null. Richer versions (multiple years, timely
disclosures, price and volume, cross-source corroboration) are untested, and the argument
for them is now weaker but not closed.

**And the held-out null is not a refutation.** Its interval is ±0.10, so it cannot exclude
an effect of +0.09 any more than it confirms one. The honest statement is that the train
result did not replicate on data that played no part in selecting it.

---

## 5. What the harness demonstrated

Independent of the benchmark result:

- **Every number traces to its inputs.** Weights digest, prompt SHA-256, input fields,
  dataset revision, git SHA — recorded per run. `ometsuke replay` re-derives any score
  from recorded responses with no model calls.
- **Failures are loud.** Strict parsing caught a truncation bias that would have silently
  dropped positives preferentially — 12 of 61 dev items clipped, and the clipped ones
  twice as likely to be fraud.
- **Intervals resample companies.** A behavioural test asserts the clustered interval
  comes out *wider* than the naive one, so the check cannot silently stop working.
- **Runs are durable and observable.** Per-item commits and WAL mode; a ten-hour sweep
  interrupted in hour nine keeps nine hours.
- **8,900 filings scored, entirely on local open weights, at no cost beyond electricity.**

---

## 6. If this were picked up again

In order of expected value:

1. **A frontier model on the same harness**, to separate "this benchmark is hard" from
   "this open-weight model is not strong enough". One API run would settle it, at the cost
   of the local-only constraint.
2. **Cross-source corroboration** — timely disclosures, price and volume around the filing
   date. The one part of the original thesis still untested, and the only one that brings
   in information a single filing cannot contain.
3. **The defect report upstream.** The join bug is reproducible with a one-line fix and
   affects everyone using the dataset.
4. **Re-estimating Beneish's coefficients on Japanese filings.** The 1999 US coefficients
   are applied unmodified here; whether the ratios fail or merely the weights do is
   unanswered.
