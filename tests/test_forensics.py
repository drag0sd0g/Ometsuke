"""Beneish, and the ways a ratio model quietly produces a number that means nothing.

The known-answer cases matter more than usual here. An M-score implementation with a
transposed coefficient or an inverted index still returns plausible-looking floats and
still scores an AUC; nothing about the output tells you it is wrong.
"""

from __future__ import annotations

import json

import pytest

from ometsuke.forensics import BENEISH_THRESHOLD, beneish, coverage, extract

# With every account identical across both years, seven of the eight indices are exactly
# 1.0 and the composite collapses to a number that can be worked out by hand:
#   M = -4.84 + (0.920+0.528+0.404+0.892+0.115-0.172-0.327) + 4.679*TATA
#     = -2.48 + 4.679*TATA
FLAT_M = -2.48


def _row(*, label=False, ni=50.0, cfo=50.0, **overrides):
    """A filing whose two years are identical unless a test says otherwise.

    total_assets 1000 with curr_assets 400 + ppe 300 keeps AQI's denominator off zero.
    """
    base = {
        "sales": 1000.0, "cogs": 600.0, "sga": 100.0,
        "receivables": 200.0, "curr_assets": 400.0, "ppe": 300.0,
        "total_assets": 1000.0, "curr_liab": 200.0, "noncurr_liab": 100.0,
        "depreciation": 50.0,
    }
    t = {**base, **{k: v for k, v in overrides.items() if k in base}}
    p = dict(base)
    labels = {
        "pl": {"売上高": "sales", "売上原価": "cogs", "販売費及び一般管理費": "sga",
               "当期利益": None},
        "bs": {"受取手形及び売掛金": "receivables", "流動資産": "curr_assets",
               "有形固定資産": "ppe", "総資産": "total_assets",
               "流動負債": "curr_liab", "非流動負債": "noncurr_liab"},
        "cf": {"減価償却費及び償却費": "depreciation", "営業キャッシュフロー": None},
    }
    sheets: dict[str, dict] = {"pl": {}, "bs": {}, "cf": {}}
    for field, mapping in labels.items():
        for jp, concept in mapping.items():
            if concept is None:
                continue
            sheets[field][jp] = {"CurrentYear": str(t[concept]),
                                 "Prior1Year": str(p[concept])}
    sheets["pl"]["当期利益"] = {"CurrentYear": str(ni), "Prior1Year": str(ni)}
    sheets["cf"]["営業キャッシュフロー"] = {"CurrentYear": str(cfo), "Prior1Year": str(cfo)}
    for key in ("drop_sheet",):
        overrides.pop(key, None)
    return {"label": label, **{f: json.dumps(v, ensure_ascii=False) for f, v in sheets.items()}}


# --- known answers ------------------------------------------------------------------

def test_identical_years_with_no_accruals_gives_the_hand_computed_score():
    result = beneish(_row(ni=50.0, cfo=50.0))
    assert result.m_score == pytest.approx(FLAT_M, abs=1e-9)
    assert all(result.indices[k] == pytest.approx(1.0) for k in
               ("DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "LVGI"))
    assert result.indices["TATA"] == pytest.approx(0.0)


def test_accruals_move_the_score_by_their_coefficient():
    """Net income exceeding operating cash flow by a full year of assets puts TATA at 1."""
    result = beneish(_row(ni=1050.0, cfo=50.0))
    assert result.indices["TATA"] == pytest.approx(1.0)
    assert result.m_score == pytest.approx(FLAT_M + 4.679, abs=1e-9)


def test_the_threshold_is_applied_in_the_right_direction():
    clean = beneish(_row(ni=50.0, cfo=50.0))
    accruing = beneish(_row(ni=1050.0, cfo=50.0))
    assert clean.m_score < BENEISH_THRESHOLD and clean.flags_manipulation is False
    assert accruing.m_score > BENEISH_THRESHOLD and accruing.flags_manipulation is True


def test_receivables_are_summed_across_the_accounts_filers_actually_use():
    """Japanese filers split trade receivables; taking only the first would understate it."""
    row = _row()
    bs = json.loads(row["bs"])
    bs["売掛金"] = {"CurrentYear": "30.0", "Prior1Year": "30.0"}
    bs["電子記録債権"] = {"CurrentYear": "20.0", "Prior1Year": "20.0"}
    row["bs"] = json.dumps(bs, ensure_ascii=False)
    assert extract(row)["receivables"]["t"] == pytest.approx(250.0)


# --- how it declines to answer ------------------------------------------------------

def test_a_missing_account_names_itself_rather_than_scoring():
    row = _row()
    bs = json.loads(row["bs"])
    del bs["総資産"]
    row["bs"] = json.dumps(bs, ensure_ascii=False)
    result = beneish(row)
    assert result.m_score is None
    assert result.unavailable == "total_assets"
    assert result.flags_manipulation is None


def test_nothing_is_imputed_when_a_year_is_absent():
    row = _row()
    pl = json.loads(row["pl"])
    pl["売上高"].pop("Prior1Year")
    row["pl"] = json.dumps(pl, ensure_ascii=False)
    assert beneish(row).unavailable == "sales"


def test_a_zero_denominator_is_missing_not_infinite():
    """Zero sales occurs in this dataset. An inf index sums into a finite-looking score."""
    result = beneish(_row(sales=0.0))
    assert result.m_score is None
    assert result.unavailable == "zero denominator"


def test_malformed_sheets_do_not_raise():
    assert beneish({"label": False, "bs": "not json", "pl": None, "cf": "{}"}).m_score is None


# --- the selection effect -----------------------------------------------------------

def test_coverage_reports_the_base_rate_on_both_sides_of_the_split():
    """Non-computability is not random in this dataset, so it has to be measurable."""
    rows = [_row(label=True) for _ in range(3)] + [_row(label=False)]
    broken = _row(label=False)
    broken["bs"] = "{}"
    rows.append(broken)

    report = coverage(rows)
    assert report["computable"] == 4
    assert report["fraud_rate_computable"] == pytest.approx(0.75)
    assert report["fraud_rate_dropped"] == pytest.approx(0.0)
    assert sum(report["blocked_by"].values()) == 1
