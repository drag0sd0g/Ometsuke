"""Typed access to the event log.

Every event kind is declared here rather than being a free-form string at the call site,
so a typo becomes an error instead of an event nobody ever reads back.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

RUN_STARTED = "run_started"
ITEM_STARTED = "item_started"
MODEL_CALL_REQUESTED = "model_call_requested"
MODEL_CALL_COMPLETED = "model_call_completed"
PREDICTION_EMITTED = "prediction_emitted"
ITEM_FAILED = "item_failed"
RUN_COMPLETED = "run_completed"

KINDS = frozenset({
    RUN_STARTED, ITEM_STARTED, MODEL_CALL_REQUESTED, MODEL_CALL_COMPLETED,
    PREDICTION_EMITTED, ITEM_FAILED, RUN_COMPLETED,
})


def append(
    conn: sqlite3.Connection,
    run_id: str,
    kind: str,
    payload: dict[str, Any],
    item_id: str | None = None,
    step_idx: int | None = None,
) -> int:
    if kind not in KINDS:
        raise ValueError(f"unknown event kind {kind!r}; add it to events.KINDS deliberately")
    cursor = conn.execute(
        "INSERT INTO events (run_id, item_id, step_idx, kind, payload) VALUES (?, ?, ?, ?, ?)",
        (run_id, item_id, step_idx, kind, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
    )
    return int(cursor.lastrowid)


def read(
    conn: sqlite3.Connection,
    run_id: str,
    kind: str | None = None,
    item_id: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT seq, item_id, step_idx, kind, payload FROM events WHERE run_id = ?"
    args: list[Any] = [run_id]
    if kind is not None:
        sql += " AND kind = ?"
        args.append(kind)
    if item_id is not None:
        sql += " AND item_id = ?"
        args.append(item_id)
    sql += " ORDER BY seq"
    return [
        {
            "seq": row["seq"],
            "item_id": row["item_id"],
            "step_idx": row["step_idx"],
            "kind": row["kind"],
            "payload": json.loads(row["payload"]),
        }
        for row in conn.execute(sql, args)
    ]
