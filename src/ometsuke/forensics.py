"""Classical forensic-accounting features, computed from the structured sheets.

No model calls. The point of this module is a baseline that a language model has to beat
before anyone claims a language model is doing something a ratio cannot.

Three things here are deliberate and easy to get wrong:

  1. **Nothing is imputed.** A missing account yields `None` all the way up to a missing
     M-score, and the reason is recorded. Filling a gap with a zero or a sector median
     would turn "we could not compute this" into a number that scores.
  2. **Non-computability is data.** `unavailable` names the concept that stopped the
     calculation, because *which* filings fail to parse turns out to correlate with the
     label — see `coverage()`. A model evaluated only on computable rows is evaluated on
     a different population than the published baselines used.
  3. **Degenerate arithmetic returns None, not infinity.** Zero sales, zero gross margin
     and zero asset bases all occur in this dataset. An index of `inf` propagates into a
     finite-looking M-score once multiplied and summed, so each ratio guards its own
     denominator.

Beneish's coefficients are from the 1999 paper and are not re-estimated here. Applying
US-estimated coefficients to Japanese filings is itself an assumption worth stating; the
eight indices are reported individually so they can be used without the composite.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

CURRENT = "CurrentYear"
PRIOR = "Prior1Year"

# Concept -> (sheet, candidate labels). Order matters: the first label present wins,
# except for concepts in SUMMED where every present label is added.
CONCEPTS: dict[str, tuple[str, list[str]]] = {
    "sales":        ("pl", ["売上高", "営業収益"]),
    "cogs":         ("pl", ["売上原価"]),
    "sga":          ("pl", ["販売費及び一般管理費"]),
    "net_income":   ("pl", ["当期利益", "親会社株主に帰属する当期純利益"]),
    "receivables":  ("bs", ["受取手形及び売掛金", "売掛金", "電子記録債権"]),
    "curr_assets":  ("bs", ["流動資産"]),
    "ppe":          ("bs", ["有形固定資産"]),
    "total_assets": ("bs", ["総資産"]),
    "curr_liab":    ("bs", ["流動負債"]),
    "noncurr_liab": ("bs", ["非流動負債", "固定負債"]),
    "depreciation": ("cf", ["減価償却費及び償却費"]),
    "cfo":          ("cf", ["営業キャッシュフロー"]),
}

# Japanese filers split trade receivables across several accounts and use different
# combinations, so the total is the sum of whichever are present rather than the first.
SUMMED = frozenset({"receivables"})

BENEISH_COEFFICIENTS = {
    "intercept": -4.84, "DSRI": 0.920, "GMI": 0.528, "AQI": 0.404, "SGI": 0.892,
    "DEPI": 0.115, "SGAI": -0.172, "TATA": 4.679, "LVGI": -0.327,
}

# Beneish's own cutoff: above this, the model flags possible manipulation.
BENEISH_THRESHOLD = -1.78


class InsufficientData(ValueError):
    """A required account is absent. Carries the concept that was missing."""

    def __init__(self, concept: str, year: str) -> None:
        super().__init__(f"{concept} unavailable for {year}")
        self.concept, self.year = concept, year


def _sheets(row: dict[str, Any]) -> dict[str, dict]:
    out = {}
    for field in ("bs", "pl", "cf"):
        raw = row.get(field)
        try:
            parsed = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            parsed = {}
        out[field] = parsed if isinstance(parsed, dict) else {}
    return out


def value(sheets: dict[str, dict], concept: str, year: str) -> float | None:
    """One account for one year, or None. Never raises on malformed input."""
    field, labels = CONCEPTS[concept]
    found: list[float] = []
    for label in labels:
        raw = (sheets[field].get(label) or {}).get(year)
        if raw in (None, "", "-"):
            continue
        try:
            found.append(float(raw))
        except (TypeError, ValueError):
            continue
        if concept not in SUMMED:
            break
    if not found:
        return None
    return sum(found) if concept in SUMMED else found[0]


def extract(row: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    """Every concept for both years. Missing stays missing."""
    sheets = _sheets(row)
    return {
        concept: {"t": value(sheets, concept, CURRENT), "t1": value(sheets, concept, PRIOR)}
        for concept in CONCEPTS
    }


def _need(figures: dict[str, dict[str, float | None]], concept: str, year: str) -> float:
    got = figures[concept][year]
    if got is None:
        raise InsufficientData(concept, year)
    return got


def _ratio(numerator: float, denominator: float) -> float:
    """Guarded division. A zero denominator is a missing ratio, not an infinite one."""
    if denominator == 0:
        raise InsufficientData("zero denominator", "n/a")
    return numerator / denominator


@dataclass(frozen=True)
class Beneish:
    """The eight indices and the composite. `unavailable` is set when it could not run."""

    indices: dict[str, float]
    m_score: float | None
    unavailable: str | None = None

    @property
    def flags_manipulation(self) -> bool | None:
        if self.m_score is None:
            return None
        return self.m_score > BENEISH_THRESHOLD


def beneish(row: dict[str, Any]) -> Beneish:
    """The Beneish M-score for one filing, or a recorded reason why not."""
    f = extract(row)
    try:
        sales_t, sales_p = _need(f, "sales", "t"), _need(f, "sales", "t1")
        cogs_t, cogs_p = _need(f, "cogs", "t"), _need(f, "cogs", "t1")
        recv_t, recv_p = _need(f, "receivables", "t"), _need(f, "receivables", "t1")
        ca_t, ca_p = _need(f, "curr_assets", "t"), _need(f, "curr_assets", "t1")
        ppe_t, ppe_p = _need(f, "ppe", "t"), _need(f, "ppe", "t1")
        ta_t, ta_p = _need(f, "total_assets", "t"), _need(f, "total_assets", "t1")
        cl_t, cl_p = _need(f, "curr_liab", "t"), _need(f, "curr_liab", "t1")
        ncl_t, ncl_p = _need(f, "noncurr_liab", "t"), _need(f, "noncurr_liab", "t1")
        dep_t, dep_p = _need(f, "depreciation", "t"), _need(f, "depreciation", "t1")
        sga_t, sga_p = _need(f, "sga", "t"), _need(f, "sga", "t1")
        ni_t = _need(f, "net_income", "t")
        cfo_t = _need(f, "cfo", "t")

        dsri = _ratio(_ratio(recv_t, sales_t), _ratio(recv_p, sales_p))
        gmi = _ratio(_ratio(sales_p - cogs_p, sales_p), _ratio(sales_t - cogs_t, sales_t))
        aqi = _ratio(1 - _ratio(ca_t + ppe_t, ta_t), 1 - _ratio(ca_p + ppe_p, ta_p))
        sgi = _ratio(sales_t, sales_p)
        depi = _ratio(_ratio(dep_p, dep_p + ppe_p), _ratio(dep_t, dep_t + ppe_t))
        sgai = _ratio(_ratio(sga_t, sales_t), _ratio(sga_p, sales_p))
        lvgi = _ratio(_ratio(cl_t + ncl_t, ta_t), _ratio(cl_p + ncl_p, ta_p))
        tata = _ratio(ni_t - cfo_t, ta_t)
    except InsufficientData as exc:
        return Beneish(indices={}, m_score=None, unavailable=exc.concept)

    indices = {"DSRI": dsri, "GMI": gmi, "AQI": aqi, "SGI": sgi,
               "DEPI": depi, "SGAI": sgai, "TATA": tata, "LVGI": lvgi}
    c = BENEISH_COEFFICIENTS
    m = c["intercept"] + sum(c[name] * val for name, val in indices.items())
    return Beneish(indices=indices, m_score=m)


def coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Who can be scored, who cannot, and whether that difference is random.

    It is not. On the training split the computable subset carries a materially higher
    fraud rate and a later mean fiscal year than the rows that drop out, so a score
    computed here describes a different population from the one the published baselines
    were measured on. Any comparison has to say so.
    """
    computable, blocked_by = [], {}
    for row in rows:
        result = beneish(row)
        if result.m_score is None:
            blocked_by[result.unavailable] = blocked_by.get(result.unavailable, 0) + 1
            computable.append(False)
        else:
            computable.append(True)

    def _fraud_rate(selected: bool) -> float | None:
        pairs = zip(rows, computable, strict=True)
        labels = [bool(r["label"]) for r, ok in pairs if ok is selected]
        return sum(labels) / len(labels) if labels else None

    return {
        "n": len(rows),
        "computable": sum(computable),
        "computable_share": sum(computable) / len(rows) if rows else 0.0,
        "fraud_rate_computable": _fraud_rate(True),
        "fraud_rate_dropped": _fraud_rate(False),
        "blocked_by": dict(sorted(blocked_by.items(), key=lambda kv: -kv[1])),
    }
