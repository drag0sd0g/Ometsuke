"""Prompts, and the variants that isolate one variable each.

`baseline` is a faithful port of Sakana's `prompt/fraud_detection.yaml`. It is the
control, and it is never edited — if it changes, nothing measured against it is
comparable any more.

Two deliberate deviations from their version, both recorded because they change what is
being compared:

  1. **Output contract.** They ask for `{reasoning, prob, prediction}` and regex-scrape
     it out of prose. We ask for `{score, label, rationale_ja, evidence}` and parse it
     strictly. Same information, but parse failure becomes an error instead of a silent
     drop.
  2. **`meta` is excluded by default**, matching their default sheets
     (`summary bs pl cf`). This matters more than it looks: `meta` carries
     当事業年度終了日, and filing date alone scores ROC-AUC 0.635 on this test split.
     Including it would hand the model the single strongest shortcut in the dataset.

WHY THE VARIANTS EXIST. On the first open-weight dev run the model emitted three distinct
scores across 61 filings — 15, 85 and 95 — with 72% of filings at exactly 85. ROC-AUC is a
ranking metric, so a three-valued score gives the curve three points and caps the
achievable number regardless of how good the underlying judgement is. Each variant below
changes exactly one thing about the instruction, so that the effect on the score
distribution is attributable.

HOW TO JUDGE THEM. On the distribution, not on AUC. At n=61 the interval on AUC is about
0.3 wide, so picking the variant with the best score is fitting noise. How many distinct
values a prompt produces, and how they spread, is descriptive and needs no power at all.
Once a variant produces a genuinely graded score, *then* AUC is worth measuring — once,
on the test split.
"""

from __future__ import annotations

import hashlib
from typing import Any

DEFAULT_SHEETS = ("summary", "bs", "pl", "cf")

_SCHEMA = """\
Respond in the following format:
JSON:
```json
{
  "score": int (0-100, confidence that the report is fraudulent),
  "label": bool (true if fraudulent),
  "rationale_ja": "string, in Japanese",
  "evidence": ["quoted spans from the filing"]
}
```
The extracted securities report is as follows:
"""

# The control. Do not edit — every comparison is against this text.
BASELINE = """\
Please analyze the following information extracted from a Japanese company's securities \
report for any signs of fraudulent activities.
Please note that some data may be missing and represented as "-" due to parsing errors.
The report has been verified by a certified public accountant, and the numerical values \
are consistent and correct from a calculation perspective. Therefore, please focus your \
analysis on non-numerical inconsistencies or logical red flags that could suggest fraud.
""" + _SCHEMA

# Variable: how the score is elicited. Everything else is byte-identical to baseline.
# Tests whether the flat three-valued output is a reporting artefact rather than the
# model's actual resolution. Note the instruction to spread is itself leading — it can
# manufacture variance without adding information, which is exactly why this variant is
# judged on distribution first and only later on whether the spread carries signal.
_PLAIN_SCORE = '  "score": int (0-100, confidence that the report is fraudulent),'

_ANCHORED_SCORE = """  "score": int (0-100, confidence that the report is fraudulent). Use the whole
           range and choose a precise value rather than a round one. Calibrate against:
           0-15 nothing of note; 16-35 minor presentational concerns only; 36-55 one
           unexplained item; 56-75 several related irregularities; 76-90 a specific and
           coherent pattern; 91-100 near-certain misstatement with named evidence,"""

_CPA_FRAMING = (
    "The report has been verified by a certified public accountant, and the numerical "
    "values are consistent and correct from a calculation perspective. Therefore, please "
    "focus your analysis on non-numerical inconsistencies or logical red flags that could "
    "suggest fraud.\n"
)

ANCHORED = BASELINE.replace(_PLAIN_SCORE, _ANCHORED_SCORE)

# Variable: the auditor framing. Everything else is byte-identical to baseline.
# The removed sentence tells the model the figures are correct and to look only at
# non-numerical signals — an odd instruction when the labels come from filings whose
# numbers were precisely what got corrected.
NO_CPA_FRAMING = BASELINE.replace(_CPA_FRAMING, "")

# Both variables at once. On the dev split the two moved different things and neither
# moved the other: anchoring took distinct scores from 3 to 6 while leaving separation
# near baseline, and dropping the framing flipped the default from 72% "suspicious" to a
# near-even split with the best separation of the four. Built by composition so it cannot
# drift from either parent.
COMBINED = NO_CPA_FRAMING.replace(_PLAIN_SCORE, _ANCHORED_SCORE)

# Variable: the language of the instruction. The source document is Japanese either way.
# Sakana's *labelling* prompt was Japanese while their *eval* prompt was English; this
# tests whether that inconsistency matters.
JAPANESE = """\
以下は日本企業の有価証券報告書から抽出した情報です。不正の兆候がないか分析してください。
解析エラーにより一部のデータが欠損し「-」と表示されている場合があります。
当該報告書は公認会計士の監査を受けており、数値は計算上整合的かつ正確です。したがって、\
数値以外の不整合、または不正を示唆する論理的な兆候に着目して分析してください。
以下の形式で回答してください。
JSON:
```json
{
  "score": int (0-100、当該報告書が不正である確信度),
  "label": bool (不正であれば true),
  "rationale_ja": "文字列、日本語で記述",
  "evidence": ["報告書から引用した箇所"]
}
```
抽出された有価証券報告書は以下のとおりです。
"""

TEMPLATES: dict[str, str] = {
    "baseline": BASELINE,
    "anchored": ANCHORED,
    "no-cpa": NO_CPA_FRAMING,
    "combined": COMBINED,
    "japanese": JAPANESE,
}


def template_for(name: str) -> str:
    try:
        return TEMPLATES[name]
    except KeyError:
        raise KeyError(f"unknown prompt variant {name!r}; have {sorted(TEMPLATES)}") from None


# `meta` carries 当事業年度終了日, and filing date alone scores ROC-AUC 0.635 on the test
# split. Putting it in a prompt hands the model the dataset's strongest shortcut and makes
# any resulting number uninterpretable, so it is refused rather than merely discouraged.
FORBIDDEN_SHEETS = frozenset({"meta"})


def sheets_from(spec: str) -> tuple[str, ...]:
    """Parse a comma-separated sheet list, refusing the ones that leak the label."""
    chosen = tuple(part.strip() for part in spec.split(",") if part.strip())
    if not chosen:
        raise ValueError("no sheets selected")
    leaking = sorted(FORBIDDEN_SHEETS.intersection(chosen))
    if leaking:
        raise ValueError(
            f"refusing to build a prompt containing {leaking}: filing date alone scores "
            "ROC-AUC 0.635 on this benchmark, so a run including it measures era "
            "detection rather than fraud detection"
        )
    return chosen


def config(name: str, sheets: tuple[str, ...] = DEFAULT_SHEETS) -> dict[str, object]:
    """What identifies a prompt in a run's config.

    The digest is the part that matters. A variant name is a label a careless edit can
    keep while changing the text underneath it; the hash cannot be kept by accident, so
    two runs whose prompts differ can never share a `config_hash`. `sheets` is recorded
    alongside because the same prompt over different inputs is a different experiment.
    """
    text = template_for(name)
    return {
        "prompt_variant": name,
        "prompt_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "sheets": list(sheets),
    }


def build(item: dict[str, Any], sheets: tuple[str, ...] = DEFAULT_SHEETS,
          template: str = BASELINE) -> str:
    """Assemble a prompt. The instruction prefix is identical across items, which is what
    makes it a stable cache breakpoint: stable prefix first, filing last."""
    body = "\n".join(f"{sheet}: {item[sheet]}" for sheet in sheets if sheet in item)
    return template + "\n" + body


def builder(name: str, sheets: tuple[str, ...] = DEFAULT_SHEETS):
    """A one-argument prompt builder bound to a named variant, for `runner.record`."""
    chosen = template_for(name)

    def _build(item: dict[str, Any]) -> str:
        return build(item, sheets=sheets, template=chosen)

    return _build
