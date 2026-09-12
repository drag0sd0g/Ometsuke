"""Behavioural tests for the log: dedup, replay determinism, and loud failure."""

from __future__ import annotations

import json

import pytest

from ometsuke import db, events, runner
from ometsuke.model import ModelResponse, StubModel


def build_prompt(item):
    return f"Analyse this filing.\n\nsummary: {item['summary']}"


ITEMS = [
    {"doc_id": "S100AAAA", "summary": "revenue up", "edinet_code": "E00001"},
    {"doc_id": "S100BBBB", "summary": "revenue down", "edinet_code": "E00001"},
    {"doc_id": "S100CCCC", "summary": "revenue flat", "edinet_code": "E00002"},
    {"doc_id": "S100DDDD", "summary": "revenue up", "edinet_code": "E00003"},
]


class CountingModel(StubModel):
    def __init__(self):
        super().__init__("counting-stub")
        self.calls = 0

    def complete(self, prompt):
        self.calls += 1
        return super().complete(prompt)


class BrokenModel:
    name = "broken"

    def complete(self, prompt):
        return ModelResponse(text="I think this filing is probably fine, honestly.")


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "runs.sqlite")


def test_identical_content_is_stored_once(conn):
    first = db.put_blob(conn, "the same prompt")
    second = db.put_blob(conn, "the same prompt")
    assert first == second
    assert conn.execute("SELECT count(*) FROM blobs").fetchone()[0] == 1


def test_identical_prompts_across_items_dedupe(conn):
    """Two of the four items share a summary, so their prompts are byte-identical."""
    runner.record(conn, ITEMS, StubModel(), build_prompt, split="dev")
    prompts = conn.execute("SELECT count(*) FROM blobs").fetchone()[0]
    assert prompts < 2 * len(ITEMS), "identical prompts should collapse to one blob"


def test_replay_makes_no_model_calls(conn):
    model = CountingModel()
    run_id = runner.record(conn, ITEMS, model, build_prompt, split="dev")
    assert model.calls == len(ITEMS)
    runner.replay(conn, run_id)
    assert model.calls == len(ITEMS), "replay must not touch the model"


def test_replaying_the_same_run_twice_is_byte_identical(conn):
    run_id = runner.record(conn, ITEMS, StubModel(), build_prompt, split="dev")
    first = runner.predictions(conn, runner.replay(conn, run_id))
    second = runner.predictions(conn, runner.replay(conn, run_id))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_replay_reproduces_the_original_predictions(conn):
    run_id = runner.record(conn, ITEMS, StubModel(), build_prompt, split="dev")
    original = runner.predictions(conn, run_id)
    replayed = runner.predictions(conn, runner.replay(conn, run_id))
    assert original == replayed


def test_a_malformed_response_fails_loudly_and_is_never_silently_dropped(conn):
    run_id = runner.record(conn, ITEMS, BrokenModel(), build_prompt, split="dev")

    failures = events.read(conn, run_id, kind=events.ITEM_FAILED)
    assert len(failures) == len(ITEMS)

    with pytest.raises(ValueError, match="failed item"):
        runner.predictions(conn, run_id)

    # Deliberately acknowledging the drop is allowed; doing it by accident is not.
    assert runner.predictions(conn, run_id, allow_failures=True) == []


def test_unknown_event_kinds_are_rejected(conn):
    run_id = runner.start_run(conn, "dev", "v1", {})
    with pytest.raises(ValueError, match="unknown event kind"):
        events.append(conn, run_id, "model_call_startedd", {})


def test_scoring_end_to_end_with_clustering(conn):
    run_id = runner.record(conn, ITEMS, StubModel(), build_prompt, split="dev")
    truth = {"S100AAAA": 1, "S100BBBB": 0, "S100CCCC": 1, "S100DDDD": 0}
    groups = {item["doc_id"]: item["edinet_code"] for item in ITEMS}
    result = runner.score(conn, run_id, truth, groups=groups, draws=200)
    assert result["n"] == 4
    assert result["n_groups"] == 3
    assert 0.0 <= result["auc"]["point"] <= 1.0
    assert result["auc"]["low"] <= result["auc"]["point"] <= result["auc"]["high"]


def test_scoring_refuses_items_with_no_ground_truth(conn):
    run_id = runner.record(conn, ITEMS, StubModel(), build_prompt, split="dev")
    with pytest.raises(KeyError, match="no ground truth"):
        runner.score(conn, run_id, {"S100AAAA": 1}, draws=50)


def test_the_run_row_records_provenance(conn):
    run_id = runner.record(conn, ITEMS, StubModel(), build_prompt, split="dev",
                           dataset_ver="hf:abc123", config={"temperature": 0})
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row["split"] == "dev"
    assert row["dataset_ver"] == "hf:abc123"
    assert row["config_hash"] and row["git_sha"] and row["finished_at"]
