"""Extract the 提出理由 from each downloaded amendment — twice, deliberately.

Two readings, because the difference is itself a finding:

  window  — pdfminer over the FIRST FOUR PAGES, reproducing exactly what Sakana's
            labeller was given (`extract_text_with_pdfminer(pdf_path, max_pages=4)`).
  full    — pdfminer over the whole document.

Where 提出理由 appears in `full` but not in `window`, the label for that filing was
assigned without the labeller ever seeing the company's stated reason. Nobody has
counted how often that happens.

Emits data/teishutsu-riyu.jsonl with no label and no LLM explanation in it — this is
the pre-blinding stage, and the worksheet built from it must stay clean.

Section boundaries are detected, not assumed: a filing where the terminator is not
found is reported rather than silently truncated at some arbitrary length.
"""

import argparse
import glob
import json
import logging
import pathlib
import re

from pdfminer.high_level import extract_text
from pdfminer.pdfpage import PDFPage

logging.getLogger("pdfminer").setLevel(logging.ERROR)

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PDF_DIR = DATA / "amendments" / "pdf"
OUT = DATA / "teishutsu-riyu.jsonl"

HEADER = re.compile(r"EDINET提出書類.{0,80}?訂正(有価証券報告書|報告書)")
# An amendment of an amendment heads the section 【…の訂正理由】 rather than 【提出理由】,
# so matching only the latter silently loses those filings.
START = re.compile(r"(?:提出理由|訂正理由)\s*】?")
# Whatever comes next in a 訂正報告書: the list of corrected items, or the corrections.
TERMINATORS = ("【訂正事項】", "【訂正箇所】", "【訂正の内容】")


def clean(text: str) -> str:
    text = HEADER.sub("", text)
    return re.sub(r"[ \t　]+", "", text)


def section(text: str) -> tuple[str | None, bool]:
    """Return (提出理由 text, whether a terminator was found)."""
    match = START.search(text)
    if not match:
        return None, False
    tail = text[match.end():]
    cuts = [tail.find(t) for t in TERMINATORS if tail.find(t) >= 0]
    if cuts:
        return tail[: min(cuts)].strip(), True
    return tail[:3000].strip(), False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=4, help="labeller's window (Sakana used 4)")
    args = parser.parse_args()

    paths = sorted(glob.glob(str(PDF_DIR / "*.pdf")))
    print(f"{len(paths)} amendment PDFs")

    in_window = outside = absent = no_terminator = 0
    with OUT.open("w", encoding="utf-8") as out:
        for index, path in enumerate(paths, 1):
            doc_id = pathlib.Path(path).stem
            with open(path, "rb") as handle:
                pages = len(list(PDFPage.get_pages(handle, check_extractable=False)))
            window_text = clean(extract_text(path, maxpages=args.pages))
            window_section, window_bounded = section(window_text)

            # Reading the whole document is slow, and only two cases need it: the
            # section is missing from the window, or it runs past the page-4 boundary
            # and would be truncated mid-sentence.
            if window_section and window_bounded:
                full_section, full_bounded = window_section, True
            elif pages > args.pages:
                full_section, full_bounded = section(clean(extract_text(path)))
            else:
                full_section, full_bounded = window_section, window_bounded

            if window_section:
                in_window += 1
            elif full_section:
                outside += 1
            else:
                absent += 1
            if full_section and not full_bounded:
                no_terminator += 1

            out.write(json.dumps({
                "amendment_doc_id": doc_id,
                "pages": pages,
                "window_pages": args.pages,
                "found_in_window": window_section is not None,
                "found_in_full": full_section is not None,
                "terminator_found": full_bounded,
                "teishutsu_riyu": full_section,
                "teishutsu_riyu_window": window_section,
                "window_chars": len(window_text),
            }, ensure_ascii=False) + "\n")

            if index % 100 == 0:
                print(f"  {index}/{len(paths)}", flush=True)

    print(f"\n提出理由 inside the labeller's {args.pages}-page window : {in_window}")
    print(f"present, but OUTSIDE that window (labelled blind)      : {outside}")
    print(f"not found at all                                       : {absent}")
    print(f"section terminator not found (check these by hand)     : {no_terminator}")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
