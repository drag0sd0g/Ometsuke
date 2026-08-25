"""Download the amendment documents behind the recoverable positive labels.

For each amendment in data/amendment-map.csv this fetches two forms:

  pdf/  — what the labeller actually read. Sakana ran pdfminer over the FIRST FOUR
          PAGES of this file, so reproducing their input means reproducing that.
  csv/  — the XBRL-to-CSV bundle. Structured, so the 提出理由 can be pulled cleanly
          rather than out of PDF layout, which gives us a second reading of the same
          text and lets us measure how often the 提出理由 falls past page 4.

Content is validated, not just saved: EDINET can answer with a JSON error body under a
200, and a directory full of 300-byte "PDFs" would otherwise look like a successful run.
"""

import argparse
import concurrent.futures
import csv
import hashlib
import io
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "amendments"
LEDGER = OUT / "_ledger.jsonl"
DOC_API = "https://api.edinet-fsa.go.jp/api/v2/documents/"

KINDS = {"pdf": (2, "pdf"), "csv": (5, "zip")}


def valid(kind: str, blob: bytes) -> bool:
    if len(blob) < 1024:
        return False
    if kind == "pdf":
        return blob[:5] == b"%PDF-"
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            return any(n.endswith(".csv") for n in archive.namelist())
    except zipfile.BadZipFile:
        return False


def fetch(doc_id: str, kind: str, key: str, retries: int = 4) -> bytes:
    api_type, _ = KINDS[kind]
    query = urllib.parse.urlencode({"type": api_type, "Subscription-Key": key})
    delay = 2.0
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(f"{DOC_API}{doc_id}?{query}", timeout=180) as response:
                return response.read()
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--limit", type=int, default=None, help="stop after N amendments (smoke test)")
    args = parser.parse_args()

    key = os.environ.get("EDINET_KEY") or os.environ.get("EDINET_API_KEY")
    if not key:
        print("EDINET_KEY is not set", file=sys.stderr)
        return 2

    rows = list(csv.DictReader((DATA / "amendment-map.csv").open(encoding="utf-8")))
    doc_ids = sorted({r["amendment_doc_id"] for r in rows})
    if args.limit:
        doc_ids = doc_ids[: args.limit]
    for kind in KINDS:
        (OUT / kind).mkdir(parents=True, exist_ok=True)

    def target(doc_id: str, kind: str) -> pathlib.Path:
        return OUT / kind / f"{doc_id}.{KINDS[kind][1]}"

    jobs = [
        (doc_id, kind)
        for doc_id in doc_ids
        for kind in KINDS
        if not (target(doc_id, kind).exists() and target(doc_id, kind).stat().st_size > 1024)
    ]
    print(f"{len(doc_ids)} amendments · {len(jobs)} files to fetch", flush=True)

    def run(job: tuple[str, str]) -> dict:
        doc_id, kind = job
        try:
            blob = fetch(doc_id, kind, key)
        except Exception as exc:
            return {"doc_id": doc_id, "kind": kind, "ok": False, "error": str(exc)}
        time.sleep(args.sleep)
        if not valid(kind, blob):
            return {"doc_id": doc_id, "kind": kind, "ok": False, "error": f"invalid content ({len(blob)} bytes)"}
        target(doc_id, kind).write_bytes(blob)
        return {
            "doc_id": doc_id,
            "kind": kind,
            "ok": True,
            "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
        }

    done = failed = total_bytes = 0
    started = time.time()
    with LEDGER.open("a", encoding="utf-8") as ledger:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for result in pool.map(run, jobs):
                ledger.write(json.dumps(result) + "\n")
                done += 1
                if result["ok"]:
                    total_bytes += result["bytes"]
                else:
                    failed += 1
                    print(f"  FAIL {result['doc_id']} {result['kind']}: {result['error']}", flush=True)
                if done % 100 == 0 or done == len(jobs):
                    rate = done / max(time.time() - started, 1e-9)
                    print(
                        f"  {done}/{len(jobs)} · {total_bytes / 1e6:.0f} MB · "
                        f"{rate:.1f} files/s · ~{(len(jobs) - done) / max(rate, 1e-9) / 60:.0f} min left",
                        flush=True,
                    )

    print(f"\ndone: {done - failed} saved, {failed} failed, {total_bytes / 1e6:.0f} MB")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
