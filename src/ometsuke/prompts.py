"""Prompts. The text below is a faithful port of Sakana's `prompt/fraud_detection.yaml`,
held fixed so that the prompt is not a free variable when the model changes. The published
score is not reproduced here — it was produced by a model this project does not call — but
holding the prompt constant is what makes an open-weight run comparable at all.

Two deliberate deviations, both recorded because they change what is being compared:

  1. **Output contract.** They ask for `{reasoning, prob, prediction}` and regex-scrape
     it out of prose. We ask for `{score, label, rationale_ja, evidence}` and parse it
     strictly. Same information, but parse failure becomes an error instead of a silent
     drop.
  2. **`meta` is excluded by default**, matching their default sheets
     (`summary bs pl cf`). This matters more than it looks: `meta` carries
     当事業年度終了日, and filing date alone scores ROC-AUC 0.635 on this test split.
     Including it would hand the model the single strongest shortcut in the dataset.
"""

from __future__ import annotations

from typing import Any

DEFAULT_SHEETS = ("summary", "bs", "pl", "cf")

BASELINE = """\
Please analyze the following information extracted from a Japanese company's securities \
report for any signs of fraudulent activities.
Please note that some data may be missing and represented as "-" due to parsing errors.
The report has been verified by a certified public accountant, and the numerical values \
are consistent and correct from a calculation perspective. Therefore, please focus your \
analysis on non-numerical inconsistencies or logical red flags that could suggest fraud.
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


def build(item: dict[str, Any], sheets: tuple[str, ...] = DEFAULT_SHEETS,
          template: str = BASELINE) -> str:
    """Assemble a prompt. The instruction prefix is identical across items, which is what
    makes it a stable cache breakpoint: stable prefix first, filing last."""
    body = "\n".join(f"{sheet}: {item[sheet]}" for sheet in sheets if sheet in item)
    return template + "\n" + body
