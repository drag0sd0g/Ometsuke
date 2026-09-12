"""Provenance: a run must say exactly which bytes it scored.

These tests deliberately touch no network. What is being checked is the fingerprinting
and the refusal to guess — the revision lookup itself is exercised the first time a split
is fetched for real.
"""

from __future__ import annotations

import json

import pytest

from ometsuke import dataset


def test_fingerprint_is_stable_and_content_sensitive(tmp_path):
    a = tmp_path / "a.parquet"
    a.write_bytes(b"identical bytes")
    b = tmp_path / "b.parquet"
    b.write_bytes(b"identical bytes")
    c = tmp_path / "c.parquet"
    c.write_bytes(b"identical bytes!")

    assert dataset.fingerprint(a) == dataset.fingerprint(b)
    assert dataset.fingerprint(a) != dataset.fingerprint(c)
    assert len(dataset.fingerprint(a)) == 64


def test_version_string_is_readable_and_pinned():
    version = dataset.version_string(
        {"repo": "SakanaAI/EDINET-Bench", "revision": "b19a8c2853320f844bebdf05edc545823733041c"}
    )
    assert version == "SakanaAI/EDINET-Bench@b19a8c285332"


def test_missing_provenance_raises_rather_than_guessing(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset, "CACHE", tmp_path)
    with pytest.raises(FileNotFoundError, match="no provenance"):
        dataset.provenance("test")


def test_provenance_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset, "CACHE", tmp_path)
    payload = {"repo": dataset.REPO, "ref": dataset.PARQUET_REF, "revision": "deadbeef" * 5,
               "split": "test", "file_sha256": "0" * 64, "rows": 224}
    (tmp_path / "fraud_detection-test.provenance.json").write_text(json.dumps(payload))
    assert dataset.provenance("test") == payload
