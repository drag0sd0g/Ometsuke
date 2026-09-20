"""The event log: append-only run history in a single SQLite file.

Phase 1 runs one step per item, but the schema carries `step_idx` so the multi-step
agent in Phase 3 needs no migration.

Prompts and responses are not stored inline. They go in `blobs`, addressed by SHA-256,
and events reference them by hash. Two consequences, both deliberate:

  * identical prompts recur constantly across items (the instruction prefix is the same
    every time), so the database stays small;
  * "did the prompt change between these two runs?" becomes a hash comparison rather
    than a diff.
"""

from __future__ import annotations

import hashlib
import pathlib
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id       TEXT PRIMARY KEY,
  dataset_ver  TEXT NOT NULL,      -- HF revision, or a local fingerprint
  split        TEXT NOT NULL,      -- 'dev' | 'test' | 'oot-2026'
  config_hash  TEXT NOT NULL,      -- sha256 of the resolved config
  git_sha      TEXT NOT NULL,
  started_at   TEXT NOT NULL,
  finished_at  TEXT
);

CREATE TABLE IF NOT EXISTS events (
  seq       INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id    TEXT NOT NULL REFERENCES runs(run_id),
  item_id   TEXT,                  -- NULL for run-level events
  step_idx  INTEGER,
  kind      TEXT NOT NULL,
  payload   TEXT NOT NULL          -- JSON; blob refs, never blob bodies
);

CREATE TABLE IF NOT EXISTS blobs (
  sha256  TEXT PRIMARY KEY,
  body    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS events_run_seq ON events (run_id, seq);
CREATE INDEX IF NOT EXISTS events_run_item ON events (run_id, item_id, seq);
"""


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def connect(path: str | pathlib.Path) -> sqlite3.Connection:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets a reader inspect a run while it is still being written. Without it, the
    # writer holds an exclusive lock for the whole run — which for a 15-hour sweep means
    # no progress checks at all.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


def put_blob(conn: sqlite3.Connection, body: str) -> str:
    """Store a blob and return its hash. Identical content is stored exactly once."""
    digest = sha256(body)
    conn.execute("INSERT OR IGNORE INTO blobs (sha256, body) VALUES (?, ?)", (digest, body))
    return digest


def get_blob(conn: sqlite3.Connection, digest: str) -> str:
    row = conn.execute("SELECT body FROM blobs WHERE sha256 = ?", (digest,)).fetchone()
    if row is None:
        raise KeyError(f"blob {digest} not in the log")
    return row["body"]
