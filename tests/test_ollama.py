"""The local client: what it records, and how it fails.

Every test here is about a way a fifteen-hour unattended run can produce a wrong number
rather than an error. None of them contact a server.
"""

from __future__ import annotations

import json

import pytest

from ometsuke import db, events, runner
from ometsuke.model import VerdictParseError, parse_verdict
from ometsuke.ollama import OllamaError, OllamaModel, weights_digest

DIGEST = "sha256-" + "9" * 64
OTHER = "sha256-" + "a" * 64


def _payload(**overrides):
    body = {
        "response": '```json\n{"score": 42, "label": false}\n```',
        "prompt_eval_count": 6462,
        "eval_count": 496,
        "total_duration": 14_900_000_000,
        "done_reason": "stop",
    }
    body.update(overrides)
    return body


def _client(monkeypatch, **overrides):
    """An OllamaModel whose transport is replaced by a canned response."""
    calls: list[dict] = []

    def fake_post(host, path, body, timeout):
        calls.append({"host": host, "path": path, "body": body, "timeout": timeout})
        if path == "/api/show":
            return {"modelfile": f"FROM /models/blobs/{DIGEST}\n"}
        return _payload(**overrides)

    monkeypatch.setattr("ometsuke.ollama._post", fake_post)
    return OllamaModel(tag="ometsuke-eval"), calls


# --- what gets recorded -------------------------------------------------------------

def test_maps_every_field_the_event_log_stores(monkeypatch):
    model, _ = _client(monkeypatch)
    response = model.complete("prompt")
    assert response.input_tokens == 6462
    assert response.output_tokens == 496
    assert response.latency_ms == 14_900
    assert response.stop_reason == "stop"


def test_cache_read_tokens_is_zero_rather_than_invented(monkeypatch):
    """Ollama reuses the KV cache but never reports it. Any other value would be fiction."""
    model, _ = _client(monkeypatch)
    assert model.complete("prompt").cache_read_tokens == 0


def test_name_carries_the_weights_not_just_the_tag(monkeypatch):
    model, _ = _client(monkeypatch)
    assert model.name == f"ometsuke-eval@{DIGEST}"


def test_same_tag_on_different_weights_does_not_collide(monkeypatch):
    """Rebuilding a Modelfile reuses the tag. Two such runs must stay distinguishable."""
    model, _ = _client(monkeypatch)
    rebuilt = OllamaModel(tag="ometsuke-eval", digest=OTHER)
    assert model.name != rebuilt.name
    assert runner.config_hash(model.config()) != runner.config_hash(rebuilt.config())


def test_thinking_is_suppressed_on_every_call(monkeypatch):
    """A reasoning model left to think spends its whole budget before answering."""
    model, calls = _client(monkeypatch)
    model.complete("prompt")
    generate = [c for c in calls if c["path"] == "/api/generate"][0]
    assert generate["body"]["think"] is False
    assert model.config()["think"] is False


def test_timeout_default_survives_the_longest_filing(monkeypatch):
    """~62k tokens is ~80s of prefill before a token is generated. A chat-tuned timeout
    would fail on long filings only — and long filings are not a random subset."""
    model, calls = _client(monkeypatch)
    model.complete("prompt")
    assert [c for c in calls if c["path"] == "/api/generate"][0]["timeout"] >= 300


# --- how it fails -------------------------------------------------------------------

def test_unidentifiable_weights_are_refused_not_recorded_as_unknown(monkeypatch):
    monkeypatch.setattr("ometsuke.ollama._post", lambda *a, **k: {"modelfile": "FROM scratch"})
    with pytest.raises(OllamaError, match="weights digest"):
        weights_digest("ometsuke-eval")


def test_server_error_is_raised_not_returned_as_a_verdict(monkeypatch):
    model, _ = _client(monkeypatch)
    monkeypatch.setattr("ometsuke.ollama._post", lambda *a, **k: {"error": "model not found"})
    with pytest.raises(OllamaError, match="model not found"):
        model.complete("prompt")


def test_an_empty_response_says_it_was_empty(monkeypatch):
    """The failure a reasoning model actually produces. Diagnosing it as malformed JSON
    sends you looking at the parser instead of the output budget."""
    model, _ = _client(monkeypatch, response="", done_reason="length")
    with pytest.raises(VerdictParseError, match="empty response"):
        parse_verdict(model.complete("prompt").text)


# --- and how the runner treats those failures ---------------------------------------

class _Model:
    name = "fake@" + DIGEST

    def __init__(self, text, stop_reason="stop"):
        self._text, self._stop = text, stop_reason

    def complete(self, prompt):
        from ometsuke.model import ModelResponse

        return ModelResponse(text=self._text, stop_reason=self._stop)


def _items(n):
    return [{"doc_id": f"S{i:06d}", "summary": "x"} for i in range(n)]


def test_a_truncated_item_is_recorded_with_its_stop_reason(tmp_path):
    """Both halves of the diagnosis — empty, and why — must sit in the log together."""
    conn = db.connect(tmp_path / "runs.sqlite")
    with pytest.raises(RuntimeError):
        runner.record(conn, _items(5), _Model("", "length"), lambda i: "p", split="dev")
    run_id = conn.execute("SELECT run_id FROM runs").fetchone()["run_id"]
    failure = events.read(conn, run_id, kind=events.ITEM_FAILED)[0]["payload"]
    assert "empty response" in failure["reason"]
    assert failure["stop_reason"] == "length"


def test_a_run_failing_identically_aborts_instead_of_burning_the_night(tmp_path):
    conn = db.connect(tmp_path / "runs.sqlite")
    with pytest.raises(RuntimeError, match="consecutive"):
        runner.record(conn, _items(500), _Model(""), lambda i: "p", split="dev",
                      max_consecutive_failures=5)
    run_id = conn.execute("SELECT run_id FROM runs").fetchone()["run_id"]
    assert len(events.read(conn, run_id, kind=events.ITEM_FAILED)) == 5
    summary = events.read(conn, run_id, kind=events.RUN_COMPLETED)[0]["payload"]
    assert summary["aborted"] is True


def test_occasional_failures_do_not_abort(tmp_path):
    """Only *consecutive* failure means misconfiguration. Scattered ones are data."""
    conn = db.connect(tmp_path / "runs.sqlite")

    class Alternating:
        name = "fake@" + DIGEST

        def __init__(self):
            self.n = 0

        def complete(self, prompt):
            from ometsuke.model import ModelResponse

            self.n += 1
            good = json.dumps({"score": 1, "label": False})
            return ModelResponse(text="" if self.n % 2 else good)

    run_id = runner.record(conn, _items(20), Alternating(), lambda i: "p", split="dev",
                           max_consecutive_failures=5)
    summary = events.read(conn, run_id, kind=events.RUN_COMPLETED)[0]["payload"]
    assert summary["items_ok"] == 10 and summary["items_failed"] == 10
    assert "aborted" not in summary


# --- durability of a partial run -----------------------------------------------------

def test_an_interrupted_run_keeps_the_items_it_finished(tmp_path):
    """A ten-hour sweep killed in hour nine must not discard all nine.

    Each item is an independent unit of work, so each is committed on its own. The check
    reads from a *separate connection*, which is the only way to prove the data is really
    committed rather than merely sitting in the writer's open transaction.
    """
    import json as _json
    import sqlite3

    from ometsuke.model import ModelResponse

    class DiesAfterThree:
        name = "fake@" + DIGEST

        def __init__(self):
            self.n = 0

        def complete(self, prompt):
            self.n += 1
            if self.n > 3:
                raise KeyboardInterrupt("simulating an interrupted sweep")
            return ModelResponse(text=_json.dumps({"score": 7, "label": False}))

    path = tmp_path / "runs.sqlite"
    conn = db.connect(path)
    with pytest.raises(KeyboardInterrupt):
        runner.record(conn, _items(50), DiesAfterThree(), lambda i: "p", split="dev")

    # A fresh connection sees only what was actually committed.
    other = sqlite3.connect(path)
    other.row_factory = sqlite3.Row
    run_id = other.execute("SELECT run_id FROM runs").fetchone()["run_id"]
    survived = other.execute(
        "SELECT COUNT(*) c FROM events WHERE run_id = ? AND kind = ?",
        (run_id, events.PREDICTION_EMITTED),
    ).fetchone()["c"]
    assert survived == 3, "completed items must survive an interruption"
    assert other.execute(
        "SELECT finished_at FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()["finished_at"] is None, "an interrupted run must not look finished"


def test_a_reader_is_not_blocked_while_a_run_is_writing(tmp_path):
    """Without WAL the writer holds an exclusive lock and progress cannot be inspected."""
    import sqlite3

    path = tmp_path / "runs.sqlite"
    writer = db.connect(path)
    writer.execute(
        "INSERT INTO runs (run_id, dataset_ver, split, config_hash, git_sha, started_at) "
        "VALUES ('r1','v','dev','c','g','t')"
    )
    # Deliberately left uncommitted, as a run in flight would be.
    reader = sqlite3.connect(path)
    reader.execute("SELECT COUNT(*) FROM runs").fetchone()  # must not raise "database is locked"
