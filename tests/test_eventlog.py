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
    prov = {"repo": "SakanaAI/EDINET-Bench", "revision": "b19a8c28" * 5,
            "file_sha256": "a" * 64, "rows": 865}
    run_id = runner.record(conn, ITEMS, StubModel(), build_prompt, split="dev",
                           dataset_ver="SakanaAI/EDINET-Bench@b19a8c28b19a",
                           config={"temperature": 0}, provenance=prov)
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (row_id := run_id,)).fetchone()
    assert row["split"] == "dev"
    assert row["dataset_ver"] == "SakanaAI/EDINET-Bench@b19a8c28b19a"
    assert row["config_hash"] and row["git_sha"] and row["finished_at"]

    started = events.read(conn, row_id, kind=events.RUN_STARTED)[0]["payload"]
    assert started["provenance"]["file_sha256"] == "a" * 64, (
        "the exact bytes scored must be recoverable from the log"
    )


def test_replay_carries_the_source_provenance_forward(conn):
    """A replayed run must not lose track of which data produced it."""
    prov = {"repo": "SakanaAI/EDINET-Bench", "revision": "c" * 40, "file_sha256": "b" * 64}
    run_id = runner.record(conn, ITEMS, StubModel(), build_prompt, split="dev",
                           dataset_ver="pinned", provenance=prov)
    replay_id = runner.replay(conn, run_id)
    started = events.read(conn, replay_id, kind=events.RUN_STARTED)[0]["payload"]
    assert started["provenance"] == prov


# --- the join every comparison goes through ------------------------------------------

def _recorded(tmp_path, items=ITEMS):
    conn = db.connect(tmp_path / "runs.sqlite")
    run_id = runner.record(conn, items, StubModel(), build_prompt, split="dev",
                           config={"prompt_variant": "no-cpa", "sheets": ["text"]})
    return conn, run_id


def test_a_missing_label_is_an_error_not_a_silent_drop(tmp_path):
    """Dropping unmatched items shrinks the denominator without saying so — the same
    class of bias as a tolerant parser, and the one this harness exists to rule out."""
    conn, run_id = _recorded(tmp_path)
    partial = {"S100AAAA": 1, "S100BBBB": 0}          # two of the four items
    with pytest.raises(KeyError, match="no ground truth for 2 item"):
        runner.joined(conn, run_id, partial)


def test_the_join_keeps_every_column_aligned(tmp_path):
    conn, run_id = _recorded(tmp_path)
    truth = {"S100AAAA": 1, "S100BBBB": 0, "S100CCCC": 1, "S100DDDD": 0}
    groups = {i["doc_id"]: i["edinet_code"] for i in ITEMS}
    data = runner.joined(conn, run_id, truth, groups=groups)
    assert len(data["doc_ids"]) == len(data["labels"]) == len(data["scores"]) == 4
    assert data["labels"] == [truth[d] for d in data["doc_ids"]]
    assert data["clusters"] == [groups[d] for d in data["doc_ids"]]


def test_score_and_distribution_read_the_same_items(tmp_path):
    """Two commands, one join. If they diverge, two published numbers describe
    different subsets while appearing to describe the same run."""
    conn, run_id = _recorded(tmp_path)
    truth = {"S100AAAA": 1, "S100BBBB": 0, "S100CCCC": 1, "S100DDDD": 0}
    assert runner.score(conn, run_id, truth)["n"] == runner.distribution(conn, run_id, truth)["n"]


def test_distribution_reports_what_produced_the_run(tmp_path):
    """A histogram without its prompt and inputs is not attributable to anything."""
    conn, run_id = _recorded(tmp_path)
    truth = {i["doc_id"]: 0 for i in ITEMS}
    report = runner.distribution(conn, run_id, truth)
    assert report["prompt_variant"] == "no-cpa"
    assert report["sheets"] == ["text"]
    assert report["failed"] == 0
    assert report["distinct"] >= 1


def test_distribution_surfaces_failures_rather_than_hiding_them(tmp_path):
    """It tolerates failures — it is a diagnostic — but must never look clean with them."""
    conn = db.connect(tmp_path / "runs.sqlite")

    class SometimesBroken(StubModel):
        def __init__(self):
            super().__init__("sometimes")
            self.n = 0

        def complete(self, prompt):
            self.n += 1
            return ModelResponse(text="not json") if self.n == 1 else super().complete(prompt)

    run_id = runner.record(conn, ITEMS, SometimesBroken(), build_prompt, split="dev")
    report = runner.distribution(conn, run_id, {i["doc_id"]: 0 for i in ITEMS})
    assert report["failed"] == 1
    assert report["n"] == 3
