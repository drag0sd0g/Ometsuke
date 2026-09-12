"""Loading EDINET-Bench, pinned to an exact upstream revision.

A run's whole claim is that its number can be re-derived. Recording the dataset as
"SakanaAI/EDINET-Bench" does not support that: if the dataset is revised upstream, a
later replay scores different rows and nothing in the log says so. So every fetch
resolves and stores the Hugging Face revision, plus a SHA-256 of the bytes actually
written locally — the second is what identifies the data when the network is gone or the
upstream repo has moved on.

`dev` is a seeded 50-item sample of *train*. It exists so prompts can be iterated
cheaply, and so the 224-item test split is touched rarely — a cost lever, but mostly
correct methodology: iterating against 224 samples is how you overfit them.

Sampling for dev is by company, not by filing, for the same reason every interval in
this project is clustered by company.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import random
import urllib.parse
import urllib.request
from typing import Any

REPO = "SakanaAI/EDINET-Bench"
# The dataset viewer's auto-converted parquet branch — what read_parquet actually reads.
PARQUET_REF = "refs/convert/parquet"
HF_API = "https://huggingface.co/api/datasets"
CACHE = pathlib.Path(__file__).resolve().parents[2] / "data" / "cache"
COLUMNS = ("meta", "summary", "bs", "pl", "cf", "text", "label", "edinet_code", "doc_id")
DEV_COMPANIES = 50
DEV_SEED = 42


def _cached(split: str) -> pathlib.Path:
    return CACHE / f"fraud_detection-{split}.parquet"


def _provenance_path(split: str) -> pathlib.Path:
    return CACHE / f"fraud_detection-{split}.provenance.json"


def fingerprint(path: pathlib.Path) -> str:
    """SHA-256 of a local file, read in chunks so a large parquet does not land in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_revision(ref: str = PARQUET_REF, timeout: int = 30) -> str:
    """The upstream commit behind a ref, so a run pins the data it actually scored."""
    url = f"{HF_API}/{REPO}/revision/{urllib.parse.quote(ref, safe='')}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)["sha"]


def version_string(provenance: dict[str, Any]) -> str:
    """Readable, sortable, and short enough for a table column."""
    return f"{provenance['repo']}@{provenance['revision'][:12]}"


def provenance(split: str) -> dict[str, Any]:
    """What exactly was scored. Raises rather than guessing if the sidecar is missing."""
    path = _provenance_path(split)
    if not path.exists():
        raise FileNotFoundError(
            f"no provenance for split {split!r}; run fetch() so the revision is recorded"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def fetch(split: str, force: bool = False) -> pathlib.Path:
    """Download one split's columns to a local parquet, once, recording what it was."""
    target = _cached(split)
    if target.exists() and _provenance_path(split).exists() and not force:
        return target
    import duckdb

    CACHE.mkdir(parents=True, exist_ok=True)
    revision = resolve_revision()
    ref = urllib.parse.quote(PARQUET_REF, safe="")
    url = (
        f"https://huggingface.co/datasets/{REPO}/resolve/{ref}"
        f"/fraud_detection/{split}/0000.parquet"
    )
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(
        f"COPY (SELECT {', '.join(COLUMNS)} FROM read_parquet('{url}')) "
        f"TO '{target}' (FORMAT parquet)"
    )
    rows = con.execute(f"SELECT count(*) FROM read_parquet('{target}')").fetchone()[0]
    _provenance_path(split).write_text(json.dumps({
        "repo": REPO,
        "ref": PARQUET_REF,
        "revision": revision,
        "split": split,
        "url": url,
        "file_sha256": fingerprint(target),
        "rows": int(rows),
        "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
    }, indent=2), encoding="utf-8")
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
