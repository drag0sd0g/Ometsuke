"""Loading EDINET-Bench, with a dev split that keeps the real test set rare.

`dev` is a seeded 50-item sample of *train*. It exists so prompts can be iterated
cheaply, and so the 224-item test split is touched rarely — a cost lever, but mostly
correct methodology: iterating against 224 samples is how you overfit them.

Sampling for dev is by company, not by filing, for the same reason every interval in
this project is clustered by company.
"""

from __future__ import annotations

import pathlib
import random
from typing import Any

REPO = "SakanaAI/EDINET-Bench"
PARQUET = (
    "https://huggingface.co/datasets/SakanaAI/EDINET-Bench/resolve/"
    "refs%2Fconvert%2Fparquet/fraud_detection"
)
CACHE = pathlib.Path(__file__).resolve().parents[2] / "data" / "cache"
COLUMNS = ("meta", "summary", "bs", "pl", "cf", "text", "label", "edinet_code", "doc_id")
DEV_COMPANIES = 50
DEV_SEED = 42


def _cached(split: str) -> pathlib.Path:
    return CACHE / f"fraud_detection-{split}.parquet"


def fetch(split: str, force: bool = False) -> pathlib.Path:
    """Download one split's columns to a local parquet, once."""
    target = _cached(split)
    if target.exists() and not force:
        return target
    import duckdb

    CACHE.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(
        f"COPY (SELECT {', '.join(COLUMNS)} FROM read_parquet('{PARQUET}/{split}/0000.parquet')) "
        f"TO '{target}' (FORMAT parquet)"
    )
    return target


def load(split: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Rows for a split. `dev` is a seeded company-level sample of train."""
    import duckdb

    source = "train" if split == "dev" else split
    path = fetch(source)
    con = duckdb.connect()
    rows = [
        dict(zip(COLUMNS, row, strict=True))
        for row in con.execute(
            f"SELECT {', '.join(COLUMNS)} FROM read_parquet('{path}') ORDER BY doc_id"
        ).fetchall()
    ]

    if split == "dev":
        companies = sorted({row["edinet_code"] for row in rows})
        chosen = set(random.Random(DEV_SEED).sample(companies, min(DEV_COMPANIES, len(companies))))
        rows = [row for row in rows if row["edinet_code"] in chosen]

    return rows[:limit] if limit else rows


def truth(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {row["doc_id"]: int(row["label"]) for row in rows}


def groups(rows: list[dict[str, Any]]) -> dict[str, str]:
    """doc_id -> company. The clustering key for every interval this project reports."""
    return {row["doc_id"]: row["edinet_code"] for row in rows}
