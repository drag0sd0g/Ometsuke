"""The prediction contract, and the model interface behind it.

Sakana's harness regex-scrapes JSON out of prose (`extract_json_between_markers`) and
returns None when that fails, which silently drops the item. Silent drops are a quiet
bias: if parsing fails more often on harder or longer filings, the reported score is
computed over an easier subset than the one advertised.

So parsing here raises. The runner catches it, records an `item_failed` event, and the
scoring path refuses to compute metrics over a run with unacknowledged failures.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class VerdictParseError(ValueError):
    """Raised when a model response cannot be read as a verdict. Never swallowed."""


@dataclass(frozen=True)
class FraudVerdict:
    score: int                        # 0-100 ordinal confidence, feeds ROC-AUC
    label: bool                       # the call itself, feeds MCC
    rationale_ja: str = ""
    evidence: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.score, int) or not 0 <= self.score <= 100:
            raise VerdictParseError(f"score must be an int in 0..100, got {self.score!r}")
        if not isinstance(self.label, bool):
            raise VerdictParseError(f"label must be a bool, got {self.label!r}")


@dataclass(frozen=True)
class ModelResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    latency_ms: int = 0
    stop_reason: str = "end_turn"


@runtime_checkable
class Model(Protocol):
    """Anything that turns a prompt into a response. The Anthropic client arrives in
    weekend 2; until then StubModel exercises the whole path without spending money."""

    name: str

    def complete(self, prompt: str) -> ModelResponse: ...


_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_verdict(text: str) -> FraudVerdict:
    """Read a verdict out of a response, or raise saying why.

    Accepts a bare JSON object or one inside a fenced block — tolerant about wrapping,
    strict about content.
    """
    candidate = text.strip()
    match = _FENCE.search(candidate)
    if match:
        candidate = match.group(1)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise VerdictParseError(f"response is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise VerdictParseError(f"expected a JSON object, got {type(data).__name__}")

    missing = {"score", "label"} - set(data)
    if missing:
        raise VerdictParseError(f"verdict is missing required field(s): {sorted(missing)}")

    evidence = data.get("evidence", [])
    if not isinstance(evidence, list) or not all(isinstance(e, str) for e in evidence):
        raise VerdictParseError("evidence must be a list of strings")

    return FraudVerdict(
        score=data["score"],
        label=data["label"],
        rationale_ja=str(data.get("rationale_ja", "")),
        evidence=list(evidence),
    )


class StubModel:
    """Deterministic, offline, and dependent only on the prompt.

    Exists so the event log, replay and scoring paths are exercised end to end without a
    single API call. Same prompt in, byte-identical response out — which is what makes
    the replay determinism test meaningful.
    """

    def __init__(self, name: str = "stub-v1") -> None:
        self.name = name

    def complete(self, prompt: str) -> ModelResponse:
        import hashlib

        digest = hashlib.sha256(prompt.encode("utf-8")).digest()
        score = digest[0] * 100 // 255
        verdict = {
            "score": score,
            "label": score >= 50,
            "rationale_ja": "スタブモデルによる決定論的な出力。",
            "evidence": [],
        }
        return ModelResponse(
            text="```json\n" + json.dumps(verdict, ensure_ascii=False) + "\n```",
            input_tokens=len(prompt) // 4,
            output_tokens=32,
        )
