"""Known-answer check on the amendment -> original mapping.

build_amendment_map.py trusts EDINET's `parentDocID` metadata field. Sakana did not:
they read the XBRL element `IdentificationOfDocumentSubjectToAmendmentDEI` out of each
amendment's own CSV. If those two disagree, our map is wrong in a way that shows up as
a plausible coverage number rather than as an error — the exact failure mode worth
spending a download on.

This downloads a random sample of amendments from data/amendment-map.csv, extracts the
XBRL element, and compares. Anything short of 100% agreement means the map cannot be
trusted and the sample below has to become the whole population.
"""

import argparse
import csv
import io
import os
import pathlib
import random
import sys
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOC_API = "https://api.edinet-fsa.go.jp/api/v2/documents/"
ELEMENT = "IdentificationOfDocumentSubjectToAmendmentDEI"


def fetch_csv_zip(doc_id: str, key: str) -> bytes:
    query = urllib.parse.urlencode({"type": 5, "Subscription-Key": key})
    with urllib.request.urlopen(f"{DOC_API}{doc_id}?{query}", timeout=120) as response:
        return response.read()


def extract_element(blob: bytes) -> str | None:
    """Pull the amended-document ID out of the XBRL-to-CSV bundle.

    The CSVs are UTF-16, tab-separated, every field quoted, one row per XBRL fact:
    element id first, value last. Element ids carry a taxonomy namespace, so the fact
    we want appears as "jpdei_cor:IdentificationOfDocumentSubjectToAmendmentDEI" —
    matching the bare name against the start of the line finds nothing, silently.
    """
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for name in archive.namelist():
            if not name.endswith(".csv"):
                continue
            text = archive.read(name).decode("utf-16", errors="replace")
            for line in text.splitlines():
                if ELEMENT not in line:
                    continue
                fields = [f.strip().strip('"') for f in line.split("\t")]
                if fields and fields[0].split(":")[-1] == ELEMENT:
                    return fields[-1]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--sample", type=int, default=15)
    parser.add_argument("--seed", type=int, default=20260823)
    parser.add_argument("--sleep", type=float, default=0.5)
    args = parser.parse_args()

    key = os.environ.get("EDINET_KEY") or os.environ.get("EDINET_API_KEY")
    if not key:
        print("EDINET_KEY is not set", file=sys.stderr)
        return 2

    rows = list(csv.DictReader((DATA / "amendment-map.csv").open(encoding="utf-8")))
    rows = [r for r in rows if r.get("csvFlag") == "1"]
    sample = random.Random(args.seed).sample(rows, min(args.sample, len(rows)))
    print(f"verifying {len(sample)} of {len(rows)} amendments (seed {args.seed})\n")

    agree = disagree = missing = 0
    for row in sample:
        amendment, expected = row["amendment_doc_id"], row["original_doc_id"]
        try:
            found = extract_element(fetch_csv_zip(amendment, key))
        except Exception as exc:
            print(f"  {amendment}  ERROR {exc}")
            missing += 1
            time.sleep(args.sleep)
            continue
        if found is None:
            print(f"  {amendment}  element absent (parentDocID said {expected})")
            missing += 1
        elif found == expected:
            agree += 1
            print(f"  {amendment}  ok  {found}")
        else:
            disagree += 1
            print(f"  {amendment}  MISMATCH  xbrl={found}  parentDocID={expected}")
        time.sleep(args.sleep)

    print(f"\nagree {agree} · disagree {disagree} · element missing/error {missing}")
    # A check that cannot fail is worthless: absent elements are a failure, not a pass.
    # The first version of this script reported PASS on a sample where it had extracted
    # the element zero times.
    if disagree or missing or agree != len(sample):
        print("FAIL — parentDocID is not confirmed against the XBRL element; the map is not trustworthy.")
        return 1
    print(f"PASS — parentDocID reproduces the XBRL element on all {agree} sampled amendments.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
