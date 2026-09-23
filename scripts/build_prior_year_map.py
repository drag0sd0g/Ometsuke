"""Find each benchmark filing's prior-year 有価証券報告書 in the archived EDINET metadata.

The prior year is taken from **EDINET, not from the benchmark**. That matters: within the
benchmark, having a second filing predicts the label perfectly — all 105 multi-filing
companies in the training split are positive, and all 253 consecutive-year pairs end in a
fraud label (docs/02 §5). Sourcing the prior year from EDINET breaks that, because every
listed company files annually whether or not it appears in the benchmark.

What it cannot break is the ten-year wall. A filing from FY2015 needs a prior year
submitted around 2015, and that is already deleted. Coverage is therefore partial and
*biased*: the retrievable subset is more recent and less fraudulent than the full split.
This script writes the coverage statistics alongside the map so the bias is recorded with
the data rather than rediscovered later. See docs/02 §5.

Output: data/prior-year-map.csv — one row per benchmark filing that has a retrievable
prior year, and data/prior-year-coverage.json — what was and was not found.
"""

import argparse
import collections
import csv
import datetime as dt
import glob
import gzip
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
META = DATA / "edinet-metadata"
ANNUAL_REPORT = "120"  # docTypeCode for 有価証券報告書

# EDINET deletes documents ten years after submission, and the metadata archive is a
# snapshot that outlives them: a record can be present while the document behind it
# returns 404. Filtering here rather than at download time keeps the map a list of things
# that actually exist, and stops the downloader spending requests on known-gone documents.
WALL_DAYS = 3652


def index_annual_reports() -> dict[tuple[str, str], dict]:
    """(edinetCode, fiscal-year-end-year) -> the annual report filed for that year.

    Keyed on `periodEnd` rather than submission date: a report filed in 2019 can cover a
    fiscal year ending 2018, and the fiscal year is what has to line up.
    """
    index: dict[tuple[str, str], dict] = {}
    for path in sorted(glob.glob(str(META / "documents-*.jsonl.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                doc = json.loads(line)
                if doc.get("docTypeCode") != ANNUAL_REPORT:
                    continue
                code, period_end = doc.get("edinetCode"), doc.get("periodEnd")
                if not code or not period_end:
                    continue
                # Later submissions win: an amended-and-refiled report supersedes.
                index[(code, period_end[:4])] = doc
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", default="train", choices=["dev", "train", "test"])
    parser.add_argument("--out", default="prior-year-map.csv")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "src"))
    from ometsuke import dataset

    index = index_annual_reports()
    print(f"indexed {len(index)} annual reports across "
          f"{len({k[0] for k in index})} companies", flush=True)

    wall = (dt.date.today() - dt.timedelta(days=WALL_DAYS)).isoformat()
    print(f"ten-year wall: prior years submitted before {wall} are already deleted",
          flush=True)

    found, missing, past_wall = [], [], []
    for row in dataset.load(args.split):
        try:
            fiscal_year = int(str(json.loads(row["meta"])["当事業年度終了日"])[:4])
        except Exception:
            continue
        prior = index.get((row["edinet_code"], str(fiscal_year - 1)))
        record = {
            "doc_id": row["doc_id"],
            "edinet_code": row["edinet_code"],
            "fiscal_year": fiscal_year,
            "label": int(bool(row["label"])),
        }
        if prior is None:
            missing.append(record)
            continue
        if prior.get("submitDateTime", "")[:10] < wall:
            # Metadata survives the document. Requesting these returns a 200 carrying a
            # JSON 404 body, which is why the downloader validates content rather than
            # trusting the status code.
            past_wall.append(record)
            missing.append(record)
            continue
        found.append({
            **record,
            "prior_doc_id": prior["docID"],
            "prior_fiscal_year": fiscal_year - 1,
            "prior_period_end": prior["periodEnd"],
            "prior_submitted": prior.get("submitDateTime", "")[:10],
            "prior_has_csv": prior.get("csvFlag", "0"),
        })

    out_path = DATA / args.out
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(found[0]))
        writer.writeheader()
        writer.writerows(found)

    def summarise(rows: list[dict]) -> dict:
        return {
            "n": len(rows),
            "fraud_rate": round(sum(r["label"] for r in rows) / len(rows), 4) if rows else None,
            "mean_fiscal_year": (round(statistics.mean(r["fiscal_year"] for r in rows), 2)
                                 if rows else None),
            "companies": len({r["edinet_code"] for r in rows}),
        }

    coverage = {
        "split": args.split,
        "retrievable": summarise(found),
        "gone": summarise(missing),
        "gone_by_fiscal_year": dict(sorted(collections.Counter(
            r["fiscal_year"] for r in missing).items())),
        "gone_because_past_wall": summarise(past_wall),
        "wall_date": wall,
        "note": (
            "The retrievable subset is more recent and less fraudulent than the full "
            "split — the ten-year wall removes positives preferentially. Compare any "
            "result against a control restricted to these same doc_ids, never against a "
            "score computed over the whole split. See docs/02 §5."
        ),
    }
    (DATA / "prior-year-coverage.json").write_text(
        json.dumps(coverage, indent=2, ensure_ascii=False), encoding="utf-8")

    total = len(found) + len(missing)
    print(f"\nprior year retrievable for {len(found)} of {total} "
          f"({100 * len(found) / total:.1f}%)")
    print(f"  retrievable: {coverage['retrievable']['fraud_rate']:.1%} fraud, "
          f"mean FY {coverage['retrievable']['mean_fiscal_year']}")
    print(f"  gone:        {coverage['gone']['fraud_rate']:.1%} fraud, "
          f"mean FY {coverage['gone']['mean_fiscal_year']}")
    print(f"  of those, {len(past_wall)} had metadata but the document is past the wall")
    print(f"\nwrote {out_path} and prior-year-coverage.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
