"""Rebuild the amendment -> original mapping that the released dataset dropped.

Reads the metadata archived by sweep_edinet_metadata.py, keeps annual amendments
(ordinanceCode 010 / formCode 030001), resolves each one's parentDocID back to the
annual report it corrects, and matches that against the 1,089 EDINET-Bench doc_ids.

Outputs
-------
data/positives.csv        the 534 positive-labelled originals (cached from Hugging Face)
data/amendment-map.csv    original doc_id -> amendment doc_id, with dates and descriptions
data/negative-hits.csv    NEGATIVE-labelled originals that were later amended (see below)

Why negative-hits.csv matters: docs/02 §8 calls negative-class error permanently
invisible, because a company that never amended has no 提出理由 to read. That is only
true from inside the dataset. The archive runs to today, so an amendment filed after
the corpus was built is visible to us and was not visible to Sakana — which makes a
slice of the negative class checkable after all.

Diagnostics, not just output: an unmatched positive can mean the ten-year retention
wall ate the amendment, or it can mean this script is wrong. Those look identical in
a coverage number, so the report separates them — misses concentrated in early years
are retention; misses spread evenly are a bug.
"""

import argparse
import collections
import csv
import glob
import gzip
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ARCHIVE = DATA / "edinet-metadata"
PARQUET = "https://huggingface.co/datasets/SakanaAI/EDINET-Bench/resolve/refs%2Fconvert%2Fparquet/fraud_detection"

ANNUAL = ("010", "030000")
ANNUAL_AMENDED = ("010", "030001")


def load_benchmark_rows() -> list[dict]:
    """The 1,089 EDINET-Bench filings, cached locally after the first fetch."""
    cache = DATA / "positives.csv"
    if cache.exists():
        with cache.open(encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    import duckdb  # only needed on the first run

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    rows = con.execute(
        f"""
        SELECT split, label, edinet_code, doc_id, fy_end FROM (
          SELECT 'train' AS split, label, edinet_code, doc_id,
                 json_extract_string(meta,'$.当事業年度終了日') AS fy_end
          FROM read_parquet('{PARQUET}/train/0000.parquet')
          UNION ALL
          SELECT 'test', label, edinet_code, doc_id,
                 json_extract_string(meta,'$.当事業年度終了日')
          FROM read_parquet('{PARQUET}/test/0000.parquet')
        ) ORDER BY split, doc_id
        """
    ).fetchall()
    records = [
        {"split": s, "label": str(lab), "edinet_code": ec, "doc_id": d, "fy_end": fy or ""}
        for s, lab, ec, d, fy in rows
    ]
    DATA.mkdir(parents=True, exist_ok=True)
    with cache.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["split", "label", "edinet_code", "doc_id", "fy_end"])
        writer.writeheader()
        writer.writerows(records)
    return records


def load_archive() -> tuple[dict[str, dict], list[dict]]:
    """Return (every archived record by docID, annual amendments)."""
    by_id: dict[str, dict] = {}
    amendments: list[dict] = []
    files = sorted(glob.glob(str(ARCHIVE / "documents-*.jsonl.gz")))
    if not files:
        sys.exit(f"no archive found in {ARCHIVE} — run sweep_edinet_metadata.py first")
    for path in files:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                doc_id = record.get("docID")
                if not doc_id:
                    continue
                by_id[doc_id] = record
                if (record.get("ordinanceCode"), record.get("formCode")) == ANNUAL_AMENDED:
                    amendments.append(record)
    return by_id, amendments


def resolve_root(record: dict, by_id: dict[str, dict], max_hops: int = 8) -> str | None:
    """Follow parentDocID until it reaches something that is not itself an amendment.

    An amendment can be amended. Matching only on the immediate parent would miss
    those chains and undercount coverage in a way that looks like data loss.
    """
    current = record
    for _ in range(max_hops):
        parent_id = current.get("parentDocID")
        if not parent_id:
            return None
        parent = by_id.get(parent_id)
        if parent is None:
            return parent_id  # outside the retrievable window; still the right id
        if (parent.get("ordinanceCode"), parent.get("formCode")) == ANNUAL:
            return parent_id
        current = parent
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    bench = load_benchmark_rows()
    positives = {r["doc_id"]: r for r in bench if r["label"] == "1"}
    negatives = {r["doc_id"]: r for r in bench if r["label"] == "0"}
    print(f"benchmark: {len(positives)} positives, {len(negatives)} negatives")

    by_id, amendments = load_archive()
    print(f"archive: {len(by_id)} documents, {len(amendments)} annual amendments")

    chained = 0
    hits: dict[str, list[dict]] = collections.defaultdict(list)
    for amendment in amendments:
        root = resolve_root(amendment, by_id)
        if root is None:
            continue
        if amendment.get("parentDocID") != root:
            chained += 1
        if root in positives or root in negatives:
            hits[root].append({"root": root, "amendment": amendment})
    print(f"amendments whose parent was itself an amendment: {chained}")

    DATA.mkdir(parents=True, exist_ok=True)
    fields = [
        "original_doc_id", "label", "split", "edinet_code", "fy_end",
        "amendment_doc_id", "submitDateTime", "docDescription", "csvFlag", "pdfFlag",
    ]

    def rows_for(source: dict[str, dict]) -> list[dict]:
        out = []
        for doc_id, bench_row in source.items():
            for hit in hits.get(doc_id, []):
                a = hit["amendment"]
                out.append({
                    "original_doc_id": doc_id,
                    "label": bench_row["label"],
                    "split": bench_row["split"],
                    "edinet_code": bench_row["edinet_code"],
                    "fy_end": bench_row["fy_end"],
                    "amendment_doc_id": a["docID"],
                    "submitDateTime": a.get("submitDateTime"),
                    "docDescription": a.get("docDescription"),
                    "csvFlag": a.get("csvFlag"),
                    "pdfFlag": a.get("pdfFlag"),
                })
        return out

    for name, source in (("amendment-map.csv", positives), ("negative-hits.csv", negatives)):
        rows = rows_for(source)
        with (DATA / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(sorted(rows, key=lambda r: (r["original_doc_id"], r["amendment_doc_id"])))
        matched = len({r["original_doc_id"] for r in rows})
        print(f"{name}: {matched}/{len(source)} originals matched, {len(rows)} amendment rows")

    # --- diagnostics: is an unmatched positive retention loss, or a bug? ---
    missed = [r for doc_id, r in positives.items() if doc_id not in hits]
    if missed and not args.quiet:
        by_year = collections.Counter(r["fy_end"][:4] for r in missed)
        found_by_year = collections.Counter(
            r["fy_end"][:4] for doc_id, r in positives.items() if doc_id in hits
        )
        print(f"\nunmatched positives: {len(missed)}")
        print("  fiscal year: matched / unmatched")
        for year in sorted(set(by_year) | set(found_by_year)):
            print(f"    {year}: {found_by_year.get(year, 0):>3} / {by_year.get(year, 0):>3}")

        # A company with no archived amendments at all is consistent with retention loss;
        # a company that clearly does have them, yet whose filing went unmatched, is not.
        amended_companies = {a.get("edinetCode") for a in amendments}
        suspicious = [r for r in missed if r["edinet_code"] in amended_companies]
        print(f"  of those, {len(suspicious)} belong to companies that DO appear in the "
              f"archive's amendments — inspect these before trusting the coverage number")

    print("\nNext: verify a subsample of parentDocID against the XBRL element "
          "IdentificationOfDocumentSubjectToAmendmentDEI before trusting this map.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
