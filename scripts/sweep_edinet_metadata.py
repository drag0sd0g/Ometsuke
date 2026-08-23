"""Sweep EDINET's document-list API day by day and archive the metadata.

Why this exists
---------------
The released EDINET-Bench parquet does not say which amendment (訂正有価証券報告書)
produced each fraud label: `ammended_doc_id` is empty for 531 of the 534 positives.
To recover the 提出理由 text the labeller actually read, we have to rebuild the
amendment -> original mapping ourselves, and the only public source for it is
EDINET's document-list API, which is queryable by submission date only.

EDINET deletes documents ten years after submission (API spec ESE140206.pdf:
「既に 10 年を経過した書類については取得できません」). Verified empirically on
2026-08-23: 2016-08-22 returns data, 2016-08-21 returns 404. The window moves
forward every day, so this archive is a decaying resource — sweep once, keep it.

Output
------
data/edinet-metadata/documents-YYYY.jsonl.gz   every record, verbatim, plus _list_date
data/edinet-metadata/_ledger.jsonl             one line per completed date (resume + audit)

The ledger is what makes the sweep restartable and checkable: it records the
API's own resultset.count alongside the number of records we wrote, so a silent
truncation shows up as a mismatch rather than as quietly missing filings.

Usage
-----
    EDINET_KEY=... uv run python scripts/sweep_edinet_metadata.py
    EDINET_KEY=... uv run python scripts/sweep_edinet_metadata.py --max-days 5   # smoke test
"""

import argparse
import concurrent.futures
import datetime
import gzip
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.edinet-fsa.go.jp/api/v2/documents.json"
OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "edinet-metadata"
LEDGER = OUT_DIR / "_ledger.jsonl"
CHUNK = 64


def fetch_day(date: datetime.date, key: str, retries: int = 5) -> dict:
    query = urllib.parse.urlencode({"date": date.isoformat(), "type": 2, "Subscription-Key": key})
    url = f"{API}?{query}"
    delay = 1.0
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"HTTP {exc.code} for {date}") from exc
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"exhausted retries for {date}")


def completed_dates() -> set[str]:
    if not LEDGER.exists():
        return set()
    done = set()
    with LEDGER.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                done.add(json.loads(line)["date"])
    return done


def write_day(day: datetime.date, payload: dict) -> int:
    metadata = payload.get("metadata", {})
    results = payload.get("results") or []
    claimed = metadata.get("resultset", {}).get("count")

    if results:
        path = OUT_DIR / f"documents-{day.year}.jsonl.gz"
        with gzip.open(path, "at", encoding="utf-8") as handle:
            for record in results:
                record["_list_date"] = day.isoformat()
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "date": day.isoformat(),
                    "status": str(metadata.get("status")),
                    "claimed_count": claimed,
                    "written": len(results),
                    "ok": claimed is None or claimed == len(results),
                }
            )
            + "\n"
        )
    return len(results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2016-08-22", help="first list date (default: retention wall)")
    parser.add_argument("--end", default=datetime.date.today().isoformat(), help="last list date, inclusive")
    parser.add_argument("--sleep", type=float, default=0.1, help="seconds a worker pauses after each request")
    parser.add_argument("--workers", type=int, default=4, help="concurrent requests")
    parser.add_argument("--max-days", type=int, default=None, help="stop after N days (smoke test)")
    args = parser.parse_args()

    key = os.environ.get("EDINET_KEY") or os.environ.get("EDINET_API_KEY")
    if not key:
        print("EDINET_KEY is not set", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    start = datetime.date.fromisoformat(args.start)
    end = datetime.date.fromisoformat(args.end)
    done = completed_dates()

    pending = []
    day = start
    while day <= end:
        if day.isoformat() not in done:
            pending.append(day)
        day += datetime.timedelta(days=1)
    if args.max_days:
        pending = pending[: args.max_days]

    total_days = (end - start).days + 1
    print(f"window {start}..{end} = {total_days} days; {len(done)} already done; {len(pending)} to fetch", flush=True)

    def fetch_one(target: datetime.date) -> tuple[datetime.date, dict]:
        payload = fetch_day(target, key)
        time.sleep(args.sleep)
        return target, payload

    written_total = 0
    index = 0
    started = time.time()

    # Fetched concurrently, written from this thread only: the gzip files and
    # the ledger have exactly one writer, and days land in calendar order.
    for offset in range(0, len(pending), CHUNK):
        chunk = pending[offset : offset + CHUNK]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            fetched = list(pool.map(fetch_one, chunk))

        for target, payload in fetched:
            index += 1
            written_total += write_day(target, payload)

        rate = index / max(time.time() - started, 1e-9)
        remaining = (len(pending) - index) / max(rate, 1e-9)
        print(
            f"  {index}/{len(pending)} days · {written_total} records · at {chunk[-1]}"
            f" · {rate:.2f} days/s · ~{remaining / 60:.0f} min left",
            flush=True,
        )

    print(f"done: {index} days fetched, {written_total} records written", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
