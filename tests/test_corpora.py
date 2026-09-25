"""Tests for the BBQ and SMS importers and their scoring.

Neither corpus is committed, so the fixtures carry the real file formats and
these tests are what stands between a silent upstream schema change and a
quietly different dataset.
"""
import json
import os

import pytest

from analysis import corpora
from lab.corpora import bbq, sms

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ----------------------------------------------------------------------- BBQ


def test_bbq_fixture_imports():
    rows = bbq.load(bbq.FIXTURE)
    assert len(rows) == 5
    assert {r["condition"] for r in rows} == {"ambiguous", "disambiguated"}


def test_every_row_identifies_its_unknown_option():
    """Losing it makes abstention unmeasurable, which is most of BBQ."""
    for row in bbq.load(bbq.FIXTURE):
        assert row["unknown_option"] is not None
        assert row["options"][row["unknown_option"]]


@pytest.mark.parametrize(
    "text", ["Unknown", "Can't be determined", "Not enough info", "Cannot be determined"]
)
def test_unknown_markers_are_recognised(text):
    assert bbq.is_unknown(text)


@pytest.mark.parametrize("text", ["The grandfather", "The Somali man", "Reykjavik"])
def test_named_people_are_not_unknown(text):
    assert not bbq.is_unknown(text)


def test_every_row_identifies_the_stereotype_option():
    """The direction of a wrong answer is the bias signal; without this the
    import cannot support the claim it exists for."""
    for row in bbq.load(bbq.FIXTURE):
        assert row["stereotype_option"] is not None
        assert row["stereotype_option"] != row["unknown_option"]


def test_a_schema_change_fails_loudly():
    with pytest.raises(ValueError, match="missing"):
        bbq.convert({"context": "c", "question": "q"}, 0)


def test_ambiguous_rows_have_the_unknown_option_as_gold():
    for row in bbq.load(bbq.FIXTURE):
        if row["condition"] == "ambiguous":
            assert row["gold"] == row["unknown_option"]
            assert row["abstention_is_correct"]


# ----------------------------------------------------------------------- SMS


def test_sms_fixture_imports():
    rows = sms.load(sms.FIXTURE)
    assert len(rows) == 8
    assert sum(1 for r in rows if r["is_spam"]) == 4


def test_an_unexpected_label_fails_loudly(tmp_path):
    path = tmp_path / "bad.tsv"
    path.write_text("maybe\tsomething\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not ham or spam"):
        sms.load(str(path))


def test_duplicates_are_flagged_and_kept_by_default(tmp_path):
    path = tmp_path / "dup.tsv"
    path.write_text("ham\tsame text\nham\tsame text\n", encoding="utf-8")
    kept = sms.load(str(path))
    assert len(kept) == 2
    assert kept[1]["duplicate_of"] == kept[0]["id"]
    assert len(sms.load(str(path), dedupe=True)) == 1


def test_summary_reports_the_base_rate():
    got = sms.summarise(sms.load(sms.FIXTURE))
    assert got["base_rate"] == 0.5
    assert got["n"] == 8


# ------------------------------------------------------------------- scoring


def test_abstention_is_not_counted_twice_on_ambiguous_items():
    rows = bbq.load(bbq.FIXTURE)
    chosen = {r["id"]: r["gold"] for r in rows}
    scored = corpora.score_bbq(rows, chosen)
    assert "abstention_rate" not in scored["ambiguous"]
    assert "abstention_rate" in scored["disambiguated"]


def test_a_stereotype_directed_guess_is_counted_and_intervalled():
    rows = bbq.load(bbq.FIXTURE)
    chosen = {r["id"]: r["gold"] for r in rows}
    target = next(r for r in rows if r["condition"] == "ambiguous")
    chosen[target["id"]] = target["stereotype_option"]
    block = corpora.score_bbq(rows, chosen)["ambiguous"]["unsupported_guesses"]
    assert block["hits"] == 1 and block["n"] == 1
    assert block["ci95"][0] < block["rate"] <= block["ci95"][1]
    assert "small n" in block["verdict"]


def test_a_direction_claim_from_few_observations_is_noted_not_measured():
    """12 of 13 is 66.7% to 98.6%: consistent with strong and with mild."""
    from jevlab.stats import wilson

    lo, hi = wilson(12, 13)
    assert lo == pytest.approx(0.6669, abs=0.001)
    assert hi == pytest.approx(0.9863, abs=0.001)
    assert corpora.SMALL_N > 13


def test_sms_scoring_reports_the_floor_and_the_asymmetry():
    rows = sms.load(sms.FIXTURE)
    probs = {r["id"]: (0.9 if r["is_spam"] else 0.1) for r in rows}
    block = corpora.score_sms(rows, probs)
    assert block["accuracy"]["rate"] == 1.0
    assert block["false_positives"] == 0 and block["false_negatives"] == 0
    assert "noise_floor" in block and "ratio_to_floor" in block
    assert "coverage" in block["high_confidence"]


def test_sms_scoring_separates_false_positives_from_false_negatives():
    rows = sms.load(sms.FIXTURE)
    probs = {r["id"]: (0.9 if r["is_spam"] else 0.9) for r in rows}
    block = corpora.score_sms(rows, probs)
    assert block["false_positives"] == 4
    assert block["false_negatives"] == 0


def test_reported_targets_are_recorded_not_treated_as_truth():
    assert corpora.REPORTED["bbq"]["questions"] == 58492
    assert corpora.REPORTED["sms"]["messages"] == 5574
    assert corpora.REPORTED["sms"]["ece"] == 0.0247


def test_demo_runs_offline(capsys):
    assert corpora.main(["--demo"]) == 0
    out = capsys.readouterr().out
    assert "NOTED, not PROVEN" in out
    assert "noise floor" in out


def test_importers_self_test_without_a_corpus(capsys):
    assert bbq.main(["--self-test"]) == 0
    assert sms.main(["--self-test"]) == 0
    assert "items from" in capsys.readouterr().out


def test_importers_refuse_to_guess_a_source():
    assert bbq.main([]) == 2
    assert sms.main([]) == 2
