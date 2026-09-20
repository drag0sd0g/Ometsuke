"""Prompt variants: each must change exactly one thing, and say so in the run config.

A variant that differs from the control in two places measures nothing attributable, and
a variant whose text drifts while its name stays put silently invalidates every earlier
comparison. Both are cheap to prevent and expensive to discover later.
"""

from __future__ import annotations

import pytest

from ometsuke import metrics, prompts

CPA_SENTENCE = "verified by a certified public accountant"


def test_every_variant_is_a_distinct_text():
    texts = {name: prompts.template_for(name) for name in prompts.TEMPLATES}
    assert len(set(texts.values())) == len(texts)


def test_every_variant_has_a_distinct_digest():
    digests = {prompts.config(n)["prompt_sha256"] for n in prompts.TEMPLATES}
    assert len(digests) == len(prompts.TEMPLATES)


def test_the_control_still_carries_the_published_framing():
    """baseline is a port of Sakana's prompt. If it drifts, nothing is comparable."""
    assert CPA_SENTENCE in prompts.BASELINE
    assert "0-100" in prompts.BASELINE


def test_no_cpa_removes_the_framing_and_nothing_else():
    assert CPA_SENTENCE not in prompts.NO_CPA_FRAMING
    # Everything either side of the removed sentence survives untouched.
    assert prompts.NO_CPA_FRAMING.startswith("Please analyze the following information")
    assert prompts.NO_CPA_FRAMING.endswith(prompts._SCHEMA)


def test_anchored_changes_only_the_score_line():
    """The auditor framing must survive, or the variant tests two things at once."""
    assert CPA_SENTENCE in prompts.ANCHORED
    assert "Calibrate against" in prompts.ANCHORED
    assert prompts.ANCHORED != prompts.BASELINE


def test_japanese_asks_for_the_same_four_fields():
    """Changing the language must not change the output contract being parsed."""
    for field in ("score", "label", "rationale_ja", "evidence"):
        assert field in prompts.JAPANESE
    assert CPA_SENTENCE not in prompts.JAPANESE
    assert "公認会計士" in prompts.JAPANESE


def test_an_unknown_variant_names_the_ones_that_exist():
    with pytest.raises(KeyError, match="unknown prompt variant"):
        prompts.template_for("no-such-variant")


def test_the_config_digest_tracks_the_text_not_the_name():
    """A name can be kept across an edit; a hash cannot be kept by accident."""
    before = prompts.config("baseline")["prompt_sha256"]
    original = prompts.TEMPLATES["baseline"]
    try:
        prompts.TEMPLATES["baseline"] = original + " "
        assert prompts.config("baseline")["prompt_sha256"] != before
    finally:
        prompts.TEMPLATES["baseline"] = original


def test_builder_binds_the_named_variant():
    item = {"summary": "S", "bs": "B", "pl": "P", "cf": "C"}
    assert prompts.builder("japanese")(item).startswith("以下は日本企業")
    assert prompts.builder("baseline")(item).startswith("Please analyze")


def test_builder_appends_only_the_requested_sheets():
    item = {"summary": "S", "bs": "B", "pl": "P", "cf": "C", "meta": "LEAK"}
    built = prompts.builder("baseline")(item)
    assert "LEAK" not in built, "meta carries the filing date, the dataset's strongest shortcut"


# --- the measurement the variants exist to move ---------------------------------------

def test_a_degenerate_score_is_reported_as_degenerate():
    """The condition on the first open-weight run: one value for most of the split."""
    report = metrics.score_distribution([0, 1, 0, 1], [85, 85, 85, 15])
    assert report["distinct"] == 2
    assert report["top_value"] == 85
    assert report["top_share"] == pytest.approx(0.75)


def test_separation_is_positive_when_positives_score_higher():
    report = metrics.score_distribution([1, 1, 0, 0], [90, 80, 20, 10])
    assert report["mean_positive"] == pytest.approx(85)
    assert report["mean_negative"] == pytest.approx(15)
    assert report["separation"] == pytest.approx(70)


def test_separation_is_none_when_a_class_is_absent():
    """At small n a split can arrive single-class; reporting 0 would read as 'no signal'."""
    assert metrics.score_distribution([1, 1], [90, 80])["separation"] is None


# --- the combined variant, and input selection ---------------------------------------

def test_combined_is_exactly_the_union_of_its_two_parents():
    """Built by composition, so it cannot drift from either variant it is compared to."""
    assert prompts.COMBINED == prompts.ANCHORED.replace(prompts._CPA_FRAMING, "")
    assert prompts.COMBINED == prompts.NO_CPA_FRAMING.replace(
        prompts._PLAIN_SCORE, prompts._ANCHORED_SCORE)
    assert "Calibrate against" in prompts.COMBINED
    assert CPA_SENTENCE not in prompts.COMBINED


def test_the_cpa_constant_is_the_text_actually_in_the_control():
    """If this drifts, no-cpa silently stops removing anything and becomes baseline."""
    assert prompts._CPA_FRAMING in prompts.BASELINE
    assert prompts._PLAIN_SCORE in prompts.BASELINE


def test_meta_is_refused_because_it_carries_the_filing_date():
    with pytest.raises(ValueError, match="0.635"):
        prompts.sheets_from("summary,meta,bs")


def test_sheets_are_parsed_and_trimmed():
    assert prompts.sheets_from(" summary , text ") == ("summary", "text")


def test_an_empty_sheet_list_is_refused():
    with pytest.raises(ValueError, match="no sheets"):
        prompts.sheets_from(" , ")


def test_config_records_the_input_as_well_as_the_prompt():
    """The same prompt over different fields is a different experiment."""
    structured = prompts.config("combined", ("summary", "bs", "pl", "cf"))
    narrative = prompts.config("combined", ("text",))
    assert structured["prompt_sha256"] == narrative["prompt_sha256"]
    assert structured["sheets"] != narrative["sheets"]


def test_builder_honours_the_selected_sheets():
    item = {"summary": "S", "bs": "B", "pl": "P", "cf": "C", "text": "NARRATIVE"}
    built = prompts.builder("combined", sheets=("text",))(item)
    assert "NARRATIVE" in built and "S" not in built.split("text:")[-1].replace("NARRATIVE", "")
