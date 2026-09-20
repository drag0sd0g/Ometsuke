"""Three ways to produce predictions, only one of which spends money.

  record   calls the model and writes events
  replay   re-derives predictions from a previous run's recorded responses, no API calls
  rescore  replay, but declaring that the parsing or scoring code has changed

Stating the nuance the README has to carry: model calls are not deterministic even at
fixed settings, so *deterministic replay means replaying recorded responses, not
regenerating them*. That is precisely what makes it useful — it separates "did my
scoring logic change?" from "did the model change?", which is otherwise the confound
that burns weekends when tuning an agent across model versions.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import subprocess
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from . import db, events
from .model import Model, VerdictParseError, parse_verdict

PromptBuilder = Callable[[dict[str, Any]], str]


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def config_hash(config: dict[str, Any]) -> str:
    return db.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False))


def start_run(
    conn: sqlite3.Connection,
    split: str,
    dataset_ver: str,
    config: dict[str, Any],
    provenance: dict[str, Any] | None = None,
) -> str:
    run_id = uuid.uuid4().hex[:16]
    conn.execute(
        "INSERT INTO runs (run_id, dataset_ver, split, config_hash, git_sha, started_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, dataset_ver, split, config_hash(config), git_sha(),
         dt.datetime.now(dt.UTC).isoformat()),
    )
    events.append(conn, run_id, events.RUN_STARTED, {
        "split": split,
        "dataset_ver": dataset_ver,
        "config": config,
        # The revision and the SHA-256 of the bytes actually scored. `dataset_ver` is the
        # readable summary; this is what settles an argument about which rows a number
        # came from, and it survives the upstream repo changing underneath us.
        "provenance": provenance or {},
    })
    return run_id


def finish_run(conn: sqlite3.Connection, run_id: str, summary: dict[str, Any]) -> None:
    conn.execute("UPDATE runs SET finished_at = ? WHERE run_id = ?",
                 (dt.datetime.now(dt.UTC).isoformat(), run_id))
    events.append(conn, run_id, events.RUN_COMPLETED, summary)
    conn.commit()


def record(
    conn: sqlite3.Connection,
    items: Iterable[dict[str, Any]],
    model: Model,
    build_prompt: PromptBuilder,
    split: str,
    dataset_ver: str = "unknown",
    config: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    max_consecutive_failures: int | None = 5,
) -> str:
    """Call the model once per item, writing every prompt and response into the log.

    `max_consecutive_failures` aborts a run whose every item is failing identically — a
    wrong model name, a server that went away, an output budget too small to reach a
    verdict. The alternative is discovering at breakfast that a fifteen-hour sweep
    produced nothing. Set it to None to disable.
    """
    config = {"model": model.name, **(config or {})}
    run_id = start_run(conn, split, dataset_ver, config, provenance=provenance)
    ok = failed = consecutive = 0

    for item in items:
        item_id = item["doc_id"]
        events.append(conn, run_id, events.ITEM_STARTED, {}, item_id=item_id, step_idx=0)
        prompt = build_prompt(item)
        prompt_hash = db.put_blob(conn, prompt)
        events.append(conn, run_id, events.MODEL_CALL_REQUESTED,
                      {"model": model.name, "prompt_hash": prompt_hash},
                      item_id=item_id, step_idx=0)

        started = time.monotonic()
        response = model.complete(prompt)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        response_hash = db.put_blob(conn, response.text)
        events.append(conn, run_id, events.MODEL_CALL_COMPLETED, {
            "response_hash": response_hash,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cache_read_tokens": response.cache_read_tokens,
            "latency_ms": response.latency_ms or elapsed_ms,
            "stop_reason": response.stop_reason,
        }, item_id=item_id, step_idx=0)

        try:
            verdict = parse_verdict(response.text)
        except VerdictParseError as exc:
            failed += 1
            consecutive += 1
            events.append(conn, run_id, events.ITEM_FAILED,
                          {"reason": str(exc), "response_hash": response_hash,
                           "stop_reason": response.stop_reason},
                          item_id=item_id, step_idx=0)
            conn.commit()
            if max_consecutive_failures is not None and consecutive >= max_consecutive_failures:
                finish_run(conn, run_id, {"mode": "record", "items_ok": ok,
                                          "items_failed": failed, "aborted": True,
                                          "abort_reason": f"{consecutive} consecutive failures"})
                raise RuntimeError(
                    f"aborting run {run_id}: {consecutive} consecutive items failed to "
                    f"produce a verdict. Last reason: {exc}"
                ) from exc
            continue
        consecutive = 0
        ok += 1
        events.append(conn, run_id, events.PREDICTION_EMITTED, {
            "score": verdict.score, "label": verdict.label,
            "response_hash": response_hash,
        }, item_id=item_id, step_idx=0)
        # Each item is an independent unit of work, so each one is durable on its own.
        # Committing only at the end would mean an interruption in hour nine of a ten-hour
        # sweep discards all nine, and would hold a write lock that blocks every reader
        # for the duration.
        conn.commit()

    finish_run(conn, run_id, {"mode": "record", "items_ok": ok, "items_failed": failed})
    return run_id


def replay(
    conn: sqlite3.Connection,
    source_run_id: str,
    mode: str = "replay",
) -> str:
    """Re-derive predictions from a previous run's recorded responses. No model calls.

    `rescore` is the same operation performed after the parsing or scoring code has
    changed; the mode is recorded so the two are distinguishable later.
    """
    if mode not in {"replay", "rescore"}:
        raise ValueError("mode must be 'replay' or 'rescore'")
    source = conn.execute("SELECT * FROM runs WHERE run_id = ?", (source_run_id,)).fetchone()
    if source is None:
        raise KeyError(f"no such run: {source_run_id}")

    original_config = events.read(conn, source_run_id, kind=events.RUN_STARTED)[0]["payload"]
    run_id = start_run(
        conn, source["split"], source["dataset_ver"],
        {**original_config["config"], "mode": mode, "source_run": source_run_id},
        provenance=original_config.get("provenance"),
    )

    ok = failed = 0
    for event in events.read(conn, source_run_id, kind=events.MODEL_CALL_COMPLETED):
        item_id = event["item_id"]
        response_hash = event["payload"]["response_hash"]
        body = db.get_blob(conn, response_hash)
        try:
            verdict = parse_verdict(body)
        except VerdictParseError as exc:
            failed += 1
            events.append(conn, run_id, events.ITEM_FAILED,
                          {"reason": str(exc), "response_hash": response_hash},
                          item_id=item_id, step_idx=event["step_idx"])
            continue
        ok += 1
        events.append(conn, run_id, events.PREDICTION_EMITTED, {
            "score": verdict.score, "label": verdict.label, "response_hash": response_hash,
        }, item_id=item_id, step_idx=event["step_idx"])

    finish_run(conn, run_id,
               {"mode": mode, "source_run": source_run_id, "items_ok": ok, "items_failed": failed})
    return run_id


def predictions(
    conn: sqlite3.Connection, run_id: str, allow_failures: bool = False
) -> list[dict[str, Any]]:
    """Every prediction in a run, in item order.

    Refuses by default if any item failed. A run with silent drops scores an easier
    subset than the one advertised, and that is exactly the bias this harness exists to
    rule out — so acknowledging it has to be an explicit act.
    """
    failures = events.read(conn, run_id, kind=events.ITEM_FAILED)
    if failures and not allow_failures:
        raise ValueError(
            f"run {run_id} has {len(failures)} failed item(s): "
            f"{[f['item_id'] for f in failures][:5]}. "
            "Pass allow_failures=True to score the remainder deliberately."
        )
    return [
        {"doc_id": event["item_id"], **event["payload"]}
        for event in events.read(conn, run_id, kind=events.PREDICTION_EMITTED)
    ]


def score(
    conn: sqlite3.Connection,
    run_id: str,
    truth: dict[str, int],
    groups: dict[str, str] | None = None,
    allow_failures: bool = False,
    draws: int = 2000,
) -> dict[str, Any]:
    """AUC and MCC for a run, each with a bootstrap interval clustered by `groups`."""
    from . import metrics

    rows = predictions(conn, run_id, allow_failures=allow_failures)
    missing = [row["doc_id"] for row in rows if row["doc_id"] not in truth]
    if missing:
        raise KeyError(f"no ground truth for {len(missing)} item(s), e.g. {missing[:3]}")

    labels: Sequence[int] = [truth[row["doc_id"]] for row in rows]
    scores = [row["score"] for row in rows]
    calls = [int(bool(row["label"])) for row in rows]
    cluster = [groups[row["doc_id"]] for row in rows] if groups else None

    return {
        "run_id": run_id,
        "n": len(rows),
        "n_groups": len(set(cluster)) if cluster else None,
        "auc": metrics.bootstrap_ci(metrics.auc, labels, scores, groups=cluster, draws=draws),
        "mcc": metrics.bootstrap_ci(metrics.mcc, labels, calls, groups=cluster, draws=draws),
    }
