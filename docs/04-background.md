# Background

For engineers who build distributed systems and don't have a statistics or ML background.

Every term here is one this repository actually uses. Each entry gives a plain definition,
an analogy from systems work, and where it shows up — with the real number, so you can
follow the argument rather than take it on faith.

---

## 1. The task

**有価証券報告書 (yūka shōken hōkokusho)** — a Japanese annual securities report. The
statutory filing every listed company submits: financial statements, business description,
risk factors, governance. Typically 30,000–80,000 characters.

**EDINET** — the Japanese regulator's disclosure system. Every filing is public; there is
an API. Think of it as the authoritative log, with one catch: **documents are deleted ten
years after submission**, so the archive is a sliding window, not an append-only store.

**The benchmark task.** Given one annual report, decide: was this filing later corrected
for accounting misconduct? A binary classifier over ~1,089 filings, roughly half labelled
fraud.

**How the labels were made.** Somebody looked for 訂正報告書 (correction filings), read the
提出理由 (the company's stated reason for correcting), and had a language model judge
whether that reason was accounting misconduct. So the label is *"this filing was later
amended and an LLM judged the reason to be misconduct"* — not *"a court found fraud."*
That distinction matters whenever a result looks strange.

---

## 2. Scoring a classifier

### Why accuracy is useless

A health check that always returns `200` scores 99.9% accuracy against a service with
99.9% uptime. It has learned nothing. Any metric you can max out by always guessing the
majority class is not measuring what you think.

**Base rate** is the proportion of positives in the data. EDINET-Bench is ~49% fraud; the
real world is well under 1%. A benchmark can be a valid measuring instrument at 49% while
telling you nothing about deployment at 0.5% — see the note at the end of the README.

### ROC-AUC

**Definition that actually helps:** pick one fraudulent filing and one clean filing at
random. AUC is the probability your system gives the fraudulent one a higher score.

- `1.0` — perfect ranking
- `0.5` — a coin flip
- **below `0.5` — the system is *anti*-correlated**; inverting its output would beat it

It measures **ranking quality, not correctness**. It doesn't care where you set a
threshold, only whether the ordering is sensible — closer to "does my priority queue put
the real incidents near the front?" than "did it label this one right?"

*Here:* Beneish's M-score scores **0.436** — below chance ([03](./03-forensic-accounting-features.md)).
Filing date alone scores **0.635**.

**A trap worth knowing:** AUC depends only on the *order* of scores, so if your system
emits only three distinct values, the ranking has only three levels and AUC is capped no
matter how good the underlying judgement is. That's exactly what the first open-weight run
hit — three values across 61 filings, 72% of them identical.

### MCC (Matthews correlation coefficient)

A single number from −1 to +1 summarising a confusion matrix, which — unlike accuracy —
stays honest when the classes are imbalanced. `0` means no better than chance. You cannot
game it by always answering "no".

*Here:* published MCC on this benchmark is 0.32.

---

## 3. How much to trust a number

### Sampling variation

You measured 0.568 on 61 filings. Run it on a *different* 61 filings and you'd get
something else. The question is always: **how much else?**

### Confidence interval

A range that would contain the true value most of the time if you repeated the whole
exercise. Written `0.568 [0.409, 0.725]`. When an interval for AUC **includes 0.5**, the
data cannot distinguish your system from a coin flip — regardless of where the point
estimate landed.

### Bootstrap

You need to know how much a number wobbles across samples, but you only have one sample.
So you fake it: draw a new dataset *from your own data, with replacement*, recompute,
repeat a few thousand times, and look at the spread.

*Systems analogy:* you have one captured traffic trace and want the variance of your p99.
You can't generate real new traffic, so you resample requests from the capture you have
and recompute p99 each time. The spread across those runs is your uncertainty.

*Here:* 2,000 draws, seed 42, on every interval reported.

### Clustered resampling — the one that matters most here

**Naive bootstrap assumes every row is an independent observation. Here they aren't.**

The 534 fraudulent filings come from only **200 companies**. One company's five filings all
describe *the same scandal* in near-identical language. Treating them as five independent
observations is like treating five replicas in the same availability zone as five
independent failure domains — when the AZ goes, they all go together, and your redundancy
was never what the arithmetic claimed.

So resampling draws **whole companies**, not filings. The effect is real: the test split's
122 positives behave closer to 50 independent observations.

**The known-answer check:** a clustered interval must come out **wider** than a naive one
on the same data. If it doesn't, the clustering isn't working. That test is in the suite.

### Statistical power

Computing a p99 from ten requests gives you a number. It is noise wearing a number's
clothes.

*Here:* the test split is 224 items. At that size, an MCC "improvement" from 0.32 to 0.38
is indistinguishable from chance. Knowing this **before** spending months optimising
toward a number that cannot detectably move is the entire reason the charter insists on
error bars first.

### Paired bootstrap

Comparing two systems? Score them on the **same items** and bootstrap the *difference*.
Shared variance cancels, which makes the comparison far more sensitive than two separate
intervals.

*Systems analogy:* A/B testing by replaying one identical request trace through both
builds, rather than sampling live traffic separately for each.

*Here:* M-score versus a date-only control on the same 591 filings gives **−0.159, CI
[−0.238, −0.083]** — an interval excluding zero, so the difference is real.

---

## 4. Five ways a number lies

### Right-censoring

A filing becomes a "fraud" only once someone *discovers* the fraud and the company
corrects it — which takes years. A 2024 filing whose fraud hasn't surfaced yet looks
identical to a clean one at the moment the dataset was built.

*Systems analogy:* classifying last week's deploys as "safe" because none has caused an
outage *yet*. The slow-burn failures haven't fired.

*Here:* this is why **filing date alone scores 0.635**. Recency correlates with innocence
as an artifact of when the corpus was assembled, so any model that can infer the era gets
a third of the benchmark's signal for free.

### Selection bias (non-random missingness)

Computing latency over only the requests that returned `200`. If timeouts concentrate on
your slow endpoint, the surviving p99 is fiction.

*Here:* financial statements parse completely for **68.3%** of filings — and those rows
carry a **51.8% fraud rate against 38.7%** for the ones that drop out. Any score computed
on the parseable subset describes a different population from the published baselines.

A second instance, caught live: at a 1,024-token output budget, 12 of 61 items were cut
off — and the truncated ones were **twice as likely to be fraud**, because the model writes
more about filings it finds suspicious. A tolerant parser that silently dropped them would
have reported a score over a subset depleted of positives.

### Multiple comparisons

Check eight dashboards for anomalies at 95% confidence and you expect roughly 0.4 false
alarms from chance alone. Finding two isn't automatically signal.

*Here:* eight Beneish indices were tested and two cleared a 95% interval. That's noted
explicitly in [03](./03-forensic-accounting-features.md) §4, and the result is argued from
effect size rather than from the interval alone.

### Overfitting your dev set

Tuning a retry policy against one captured incident until it handles that incident
perfectly. You've fitted the sample, not the world.

*Here:* `dev` is 61 items with an AUC interval ~0.3 wide. Trying five prompts and keeping
the best score is choosing noise. So prompt variants are judged on **score distribution**,
which is directly observable and needs no statistical power, and AUC is reserved for the
test split, run rarely.

### Contamination

If a model was trained on text that already contains the answers, it isn't reasoning —
it's recalling. The usual defence is an **out-of-time split**: evaluate only on documents
published after the model's training cutoff. Awkward here, because right-censoring means
recent filings have had no time to *become* positives.

---

## 5. Running a language model locally

**Token** — the model's unit of work, roughly a word-piece. Japanese here runs about
**0.79 tokens per character**, so a 34,000-character filing is ~27,000 tokens.

**Context window** — how much the model can hold for a single request, prompt and answer
together. This setup uses **131,072 tokens**. Exceed it and something must be dropped —
which is why the charter insists truncation must never happen silently.

**Prefill vs decode** — two phases with completely different performance characteristics:

| | what it does | bound by | measured |
|---|---|---|---|
| **prefill** | reads the whole prompt at once | compute — embarrassingly parallel matrix work | **782 tok/s** |
| **decode** | generates output one token at a time, each depending on the last | memory bandwidth — inherently serial | **49 tok/s** |

*Systems analogy:* prefill is a batch job you can parallelise; decode is a serial pipeline
where each stage waits on the previous one. This is why a long prompt with a short answer
behaves very differently from the reverse.

**KV cache** — memoised intermediate state so each new token doesn't reprocess the entire
prompt. Like session state: it grows with length, which is why a long context costs
*memory*, not just time.

**Temperature** — how much randomness goes into picking each token. `1` samples from a
distribution; `0` always takes the most likely token, making the model a deterministic
function of its input rather than a randomised one.

**Important caveat:** temperature 0 is **not** bit-reproducible. GPU scheduling and
batching still vary. That's precisely why this repo's replay re-runs *recorded responses*
rather than regenerating them — it separates "did my scoring code change?" from "did the
model change?"

**Mixture of experts (MoE)** — the model has 256 expert sub-networks and routes each token
to just 8 of them. Like consistent hashing to a shard subset: 125 billion parameters on
disk, but only a fraction read per token. It's why a 125B model runs at 49 tok/s on a
laptop at all.

**Quantization** — storing weights at reduced precision (`Q4` ≈ 4 bits instead of 16).
Same trade as `float32` over `float64`: much smaller and faster, slightly lossy.

**Open weights vs API** — the model is a file on disk with a SHA-256. An API model is an
endpoint that can change under you without notice. Same distinction as a pinned container
digest versus `:latest`, and the reason a result here can be re-derived months later.

---

## 6. The accounting side

**Accruals** — the gap between profit *reported* and cash actually *received*. Revenue
booked but not yet collected. Persistently high accruals mean earnings unsupported by
cash, which is the classic manipulation signature.

**Beneish M-score** — eight ratios comparing this year to last (receivables growth versus
sales, margin changes, asset quality, leverage, accruals), combined with fixed weights from
a 1999 paper into one number. Above −1.78 flags possible manipulation. It is the standard
textbook screen.

*Here:* it lands at **0.436 — below chance**, with accruals the most inverted of the eight.

**循環取引 (junkan torihiki)** — circular trading. Fictitious sales settled by cash moving
in a loop between colluding parties. A characteristically Japanese fraud pattern, and the
leading hypothesis for why an accruals screen fails here: it inflates revenue **and**
operating cash flow together, leaving accruals unremarkable — exactly the signature Beneish
was built to catch, neutralised.

---

## 7. Japanese terms

| | |
|---|---|
| 有価証券報告書 | annual securities report — the filing being classified |
| 訂正報告書 | correction filing — an amendment to a previous submission |
| 提出理由 | "reason for submission" — where a company states why it is correcting; the text the labels were derived from |
| 不適切な会計処理 | "inappropriate accounting treatment" — deliberately vague; covers both deliberate schemes and control failures |
| 粉飾 | window-dressing; cooking the books |
| 第三者委員会 | third-party investigation committee — nobody convenes one over a typo |
| 誤り | "error" — the word this corpus actually uses for clerical corrections (誤記 / 誤植 appear in none of 574 texts) |
| 当事業年度終了日 | fiscal year end date — the field that alone scores ROC-AUC 0.635 |
