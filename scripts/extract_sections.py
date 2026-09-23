"""Pull named XBRL text blocks out of EDINET CSV bundles, for both years of a pair.

Why not use the benchmark's own `text` field for the current year: it is Sakana's
extraction, and the prior year would be ours. Diffing two differently-extracted texts
measures the extraction difference as much as the filing difference. So both years are
taken from the same source in the same way, and the benchmark's `text` is not used here
at all.

Why these sections: the hypothesis under test is that fraud shows up as drift between
filings — specifically in how a company describes its risks and how it draws its segment
boundaries. Both are addressable by element name in the XBRL, so no layout parsing or
heuristics are involved; a section is either present under its tag or it is absent, and
absence is recorded rather than silently treated as empty.

Output: data/section-pairs.jsonl — one object per filing carrying both years' sections,
plus which sections were missing on each side.
"""

import argparse
import collections
import csv
import io
import json
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# The two the charter names. Element ids are stable across years, which is what makes a
# like-for-like diff possible at all.
SECTIONS = {
    "risks": "jpcrp_cor:BusinessRisksTextBlock",
    "segments": "jpcrp_cor:NotesSegmentInformationEtcConsolidatedFinancialStatementsTextBlock",
}

VALUE_COLUMN = 8   # 値
ELEMENT_COLUMN = 0  # 要素ID


def read_sections(bundle: pathlib.Path, wanted: dict[str, str]) -> dict[str, str]:
    """Element id -> text, for the sections present in this bundle.

    EDINET writes these as UTF-16 tab-separated. Several CSVs ship per bundle (audit
    report, cover page, the report itself); the wanted elements live in the `asr` one,
    but every CSV is scanned rather than relying on that filename convention holding.
    """
    found: dict[str, str] = {}
    with zipfile.ZipFile(bundle) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".csv"):
                continue
            text = archive.read(name).decode("utf-16", errors="ignore")
            for row in csv.reader(io.StringIO(text), delimiter="\t"):
                if len(row) <= VALUE_COLUMN:
                    continue
                for label, element in wanted.items():
                    if row[ELEMENT_COLUMN] == element and row[VALUE_COLUMN].strip():
                        # First occurrence wins: consolidated precedes non-consolidated.
                        found.setdefault(label, row[VALUE_COLUMN])
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", default="prior-year-map.csv")
    parser.add_argument("--current", default="current-years",
                        help="directory under data/ holding the current-year bundles")
    parser.add_argument("--prior", default="prior-years")
    parser.add_argument("--out", default="section-pairs.jsonl")
    args = parser.parse_args()

    rows = list(csv.DictReader((DATA / args.map).open(encoding="utf-8")))
    seen: set[str] = set()
    pairs = [r for r in rows if not (r["doc_id"] in seen or seen.add(r["doc_id"]))]
    print(f"{len(pairs)} filings to pair", flush=True)

    out_path = DATA / args.out
    written = 0
    missing = collections.Counter()
    with out_path.open("w", encoding="utf-8") as handle:
        for row in pairs:
            current = DATA / args.current / f"{row['doc_id']}.zip"
            prior = DATA / args.prior / f"{row['prior_doc_id']}.zip"
            if not current.exists() or not prior.exists():
                missing["bundle absent"] += 1
                continue
            now = read_sections(current, SECTIONS)
            then = read_sections(prior, SECTIONS)
            absent = [k for k in SECTIONS if k not in now or k not in then]
            for k in absent:
                missing[f"section {k}"] += 1
            handle.write(json.dumps({
                "doc_id": row["doc_id"],
                "label": int(row["label"]),
                "edinet_code": row["edinet_code"],
                "fiscal_year": int(row["fiscal_year"]),
                "prior_doc_id": row["prior_doc_id"],
                "current": now,
                "prior": then,
                "sections_missing": absent,
            }, ensure_ascii=False) + "\n")
            written += 1
            if written % 100 == 0:
                print(f"  {written}/{len(pairs)}", flush=True)

    print(f"\nwrote {written} pairs to {out_path}")
    if missing:
        print("gaps:", dict(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
