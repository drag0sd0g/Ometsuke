"""Select decoy amendments so the audit is a blind classification rather than a confirmation.

Every item in the positive sample is, by construction, a filing the labeller flagged. A
rater who knows that knows the answer key before reading a word. Decoys are amendments
the labeller did NOT flag, shuffled in and indistinguishable at classification time.

Source: data/negative-hits.csv — negative-labelled filings that were later amended.
These are provably unflagged, because prepare_nonfraud.py excludes any company whose
EDINET code appears anywhere in the fraud set. If the labeller had flagged one of these
amendments, the company could not be in the negative class at all.

One amendment per filing, so decoys carry no distinguishing sibling structure.
"""

import argparse
import csv
import pathlib
import random

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--count", type=int, default=15)
    parser.add_argument("--seed", type=int, default=20260823)
    args = parser.parse_args()

    rows = list(csv.DictReader((DATA / "negative-hits.csv").open(encoding="utf-8")))
    by_original: dict[str, list[dict]] = {}
    for row in rows:
        by_original.setdefault(row["original_doc_id"], []).append(row)

    # Keep the decoys inside the date range of the real sample, so submission date is
    # not itself a tell.
    mapped = list(csv.DictReader((DATA / "amendment-map.csv").open(encoding="utf-8")))
    lo = min(r["submitDateTime"] for r in mapped if r["submitDateTime"])
    hi = max(r["submitDateTime"] for r in mapped if r["submitDateTime"])

    eligible = sorted(
        original for original, amendments in by_original.items()
        if any(lo <= (a["submitDateTime"] or "") <= hi for a in amendments)
    )
    print(f"{len(by_original)} amended negatives; {len(eligible)} within the sample's date range "
          f"({lo[:10]} .. {hi[:10]})")

    rng = random.Random(args.seed)
    chosen = rng.sample(eligible, min(args.count, len(eligible)))

    picked = []
    for original in sorted(chosen):
        candidates = [a for a in by_original[original] if lo <= (a["submitDateTime"] or "") <= hi]
        picked.append(sorted(candidates, key=lambda a: a["submitDateTime"])[0])

    out = DATA / "decoy-map.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(picked)
    print(f"selected {len(picked)} decoys -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
