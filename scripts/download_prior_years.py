"""Download the 有価証券報告書 named in data/prior-year-map.csv — either year.

`--column prior_doc_id` fetches the prior year, `--column doc_id` the benchmark filing
itself. Both are needed: diffing Sakana's extraction of one year against ours of the
other would measure the extraction difference as much as the filing difference.

Fetches the XBRL-to-CSV bundle (API type 5) rather than the PDF. The benchmark's own
`text` field comes from structured extraction, so taking the structured form here keeps
both years in the same representation — a diff between a CSV-derived text and a
PDF-derived one would partly measure the extraction difference.

Content is validated rather than merely saved: EDINET can answer with a JSON error body
under a 200 status, and a directory of 300-byte "zips" would otherwise look like a
successful run.

Resumable. Files already present and non-trivial are skipped, so an interrupted run
continues rather than restarting — the archive is on a ten-year clock and re-fetching is
not always possible.
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
DOC_API_OUT = {"prior_doc_id": "prior-years", "doc_id": "current-years"}
DOC_API = "https://api.edinet-fsa.go.jp/api/v2/documents/"
CSV_TYPE = 5


def valid(blob: bytes) -> bool:
    if len(blob) < 1024:
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            return any(name.endswith(".csv") for name in archive.namelist())
    except zipfile.BadZipFile:
        return False


def fetch(doc_id: str, key: str, retries: int = 4) -> bytes:
    query = urllib.parse.urlencode({"type": CSV_TYPE, "Subscription-Key": key})
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
    parser.add_argument("--limit", type=int, default=None, help="stop after N (smoke test)")
    parser.add_argument("--map", default="prior-year-map.csv")
    parser.add_argument("--column", default="prior_doc_id", choices=list(DOC_API_OUT),
                        help="which column of the map to download")
    args = parser.parse_args()

    key = os.environ.get("EDINET_KEY") or os.environ.get("EDINET_API_KEY")
    if not key:
        print("EDINET_KEY is not set", file=sys.stderr)
        return 2

    out_dir = DATA / DOC_API_OUT[args.column]
    ledger_path = out_dir / "_ledger.jsonl"
    rows = list(csv.DictReader((DATA / args.map).open(encoding="utf-8")))
    doc_ids = sorted({r[args.column] for r in rows})
    if args.limit:
        doc_ids = doc_ids[: args.limit]
    out_dir.mkdir(parents=True, exist_ok=True)

    def target(doc_id: str) -> pathlib.Path:
        return out_dir / f"{doc_id}.zip"

    jobs = [d for d in doc_ids
            if not (target(d).exists() and target(d).stat().st_size > 1024)]
    print(f"{len(rows)} filings · {len(doc_ids)} distinct prior-year documents · "
          f"{len(jobs)} to fetch", flush=True)
    if not jobs:
        print("nothing to do — all present")
        return 0

    def run(doc_id: str) -> dict:
        try:
            blob = fetch(doc_id, key)
        except Exception as exc:
            return {"doc_id": doc_id, "ok": False, "error": str(exc)}
        time.sleep(args.sleep)
        if not valid(blob):
            return {"doc_id": doc_id, "ok": False,
                    "error": f"invalid content ({len(blob)} bytes)"}
        target(doc_id).write_bytes(blob)
        return {"doc_id": doc_id, "ok": True, "bytes": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest()}

    done = failed = total_bytes = 0
    started = time.time()
    with ledger_path.open("a", encoding="utf-8") as ledger:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for result in pool.map(run, jobs):
                ledger.write(json.dumps(result) + "\n")
                done += 1
                if result["ok"]:
                    total_bytes += result["bytes"]
                else:
                    failed += 1
                    print(f"  FAIL {result['doc_id']}: {result['error']}", flush=True)
                if done % 50 == 0 or done == len(jobs):
                    rate = done / max(time.time() - started, 1e-9)
                    print(f"  {done}/{len(jobs)} · {total_bytes / 1e6:.0f} MB · "
                          f"{rate:.1f} files/s · "
                          f"~{(len(jobs) - done) / max(rate, 1e-9) / 60:.0f} min left",
                          flush=True)

    print(f"\ndone: {done - failed} saved, {failed} failed, {total_bytes / 1e6:.0f} MB")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
