"""The prediction contract: tolerant about wrapping, strict about content."""

from __future__ import annotations

import pytest

from ometsuke.model import FraudVerdict, StubModel, VerdictParseError, parse_verdict


def test_reads_a_fenced_json_block():
    verdict = parse_verdict('```json\n{"score": 80, "label": true}\n```')
    assert verdict.score == 80 and verdict.label is True


def test_reads_bare_json():
    assert parse_verdict('{"score": 10, "label": false}').score == 10


def test_reads_a_fenced_block_surrounded_by_prose():
    text = 'Here is my analysis.\n```json\n{"score": 55, "label": true}\n```\nHope that helps.'
    assert parse_verdict(text).score == 55


@pytest.mark.parametrize("text,match", [
    ("not json at all", "not JSON"),
    ('{"score": 50}', "missing required"),
    ('{"label": true}', "missing required"),
    ('["score", 50]', "expected a JSON object"),
    ('{"score": 150, "label": true}', "0..100"),
    ('{"score": "high", "label": true}', "0..100"),
    ('{"score": 50, "label": "yes"}', "must be a bool"),
    ('{"score": 50, "label": true, "evidence": "a span"}', "list of strings"),
])
def test_malformed_responses_raise_rather_than_return_none(text, match):
    with pytest.raises(VerdictParseError, match=match):
        parse_verdict(text)


def test_verdict_validates_on_construction():
    with pytest.raises(VerdictParseError):
        FraudVerdict(score=-1, label=True)


def test_stub_model_is_deterministic():
    model = StubModel()
    assert model.complete("same prompt").text == model.complete("same prompt").text
    assert model.complete("a").text != model.complete("b").text
