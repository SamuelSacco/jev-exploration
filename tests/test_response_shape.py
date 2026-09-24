"""Tests for the endpoint and position probes.

Neither can be run here, so what is tested is the item set's gradient and the
scoring logic in both directions — particularly the position arithmetic, whose
whole point is refusing to call stochasticity a position effect.
"""
import json
import os

import pytest

from analysis import response_shape as rs
from lab import exp_response_shape as ex
from lab import response_shape_items as items_mod

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------------- the items


def test_items_rebuild_byte_for_byte():
    with open(os.path.join(HERE, "lab", "response_shape_items.json"), encoding="utf-8") as fh:
        committed = json.load(fh)["items"]
    assert committed == items_mod.generate()


def test_evidence_actually_weakens_across_the_bands():
    sep = items_mod.separability(items_mod.generate())
    assert items_mod.gradient_is_monotone(sep), sep
    assert items_mod.ambiguous_is_unsolvable(sep), sep


def test_the_ambiguous_band_is_at_chance_for_a_word_counter():
    """An earlier version put a one-sided resolving sentence in this band and it
    scored 75%, above the moderate band: ambiguous in intent only."""
    sep = items_mod.separability(items_mod.generate())
    assert sep["ambiguous"] <= 0.40
    assert sep["ambiguous"] < sep["moderate"] < sep["decisive"]


def test_every_band_is_balanced_across_the_four_options():
    generated = items_mod.generate()
    for band in items_mod.BANDS:
        golds = [i["gold"] for i in generated if i["strength"] == band]
        assert len(set(golds)) == 4
        assert len(set(golds.count(g) for g in set(golds))) == 1


def test_choice_criteria_is_a_dict_and_reversing_changes_only_the_order():
    item = items_mod.generate()[0]
    forward = ex.choice_question(item, reverse=False)["criteria"]
    backward = ex.choice_question(item, reverse=True)["criteria"]
    assert isinstance(forward, dict)
    assert list(backward) == list(forward)[::-1]
    assert forward == backward  # same content, different insertion order


def test_noul_form_asks_one_question_per_option():
    item = items_mod.generate()[0]
    questions = ex.noul_questions(item)
    assert len(questions) == len(item["options"])
    assert all(q["type"] == "noul" for q in questions.values())


def test_dry_run_needs_no_credential(capsys):
    assert ex.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Total calls: 30" in out
    assert "P1_reordering_flips_more_than_repetition" in out


# ---------------------------------------------------------------- the position


def _position_block(reordered_pattern, repeat_pattern):
    """Build passes where item i flips iff the pattern says so."""
    ids = [f"rs{i:03d}" for i in range(len(reordered_pattern))]
    forward = [{i: {"choice": "billing"} for i in ids}]
    rev = [{i: {"choice": "technical" if f else "billing"} for i, f in zip(ids, reordered_pattern)}]
    rep = [{i: {"choice": "technical" if f else "billing"} for i, f in zip(ids, repeat_pattern)}]
    items = {i: {"gold": "billing", "strength": "decisive"} for i in ids}
    return {"forward": forward, "reversed": rev, "repeat": rep}, items


def test_a_flip_rate_matched_by_the_same_order_control_is_not_a_position_effect():
    """The finding the 24.7% claim cannot distinguish from noise."""
    pattern = [1] * 25 + [0] * 75
    block, items = _position_block(pattern, pattern)
    got = rs.position_effect(block, items)
    assert got["reordered"]["rate"] == 0.25
    assert got["same_order_repeat"]["rate"] == 0.25
    assert got["effect"] == 0.0
    verdict = rs.verdicts({"position": got}, 0.247)
    assert verdict["P1_reordering_flips_more_than_repetition"]["verdict"] == "REFUTED"


def test_a_real_position_effect_is_detected():
    block, items = _position_block([1] * 60 + [0] * 40, [0] * 100)
    got = rs.position_effect(block, items)
    assert got["effect"] == pytest.approx(0.60, abs=0.01)
    verdict = rs.verdicts({"position": got}, 0.247)
    assert verdict["P1_reordering_flips_more_than_repetition"]["verdict"] == "PROVEN"
    # 60% is above the reported 24.7%, so P2 fails.
    assert verdict["P2_any_position_effect_is_below_the_reported_rate"]["verdict"] == "REFUTED"


def test_a_small_real_effect_stays_below_the_reported_rate():
    block, items = _position_block([1] * 12 + [0] * 88, [0] * 100)
    got = rs.position_effect(block, items)
    verdict = rs.verdicts({"position": got}, 0.247)
    assert verdict["P1_reordering_flips_more_than_repetition"]["verdict"] == "PROVEN"
    assert verdict["P2_any_position_effect_is_below_the_reported_rate"]["verdict"] == "PROVEN"


# --------------------------------------------------------------- the endpoints


def _endpoint_passes(zero_on_gold=False):
    answers = {}
    for band, zeros in (("decisive", 3), ("moderate", 2), ("ambiguous", 0)):
        for i in range(4):
            qid = f"{band}{i}"
            probs = {"billing": 0.7, "technical": 0.3, "sales": 0.0, "account": 0.0}
            if zeros == 0:
                probs = {"billing": 0.4, "technical": 0.3, "sales": 0.2, "account": 0.1}
            if zero_on_gold and band == "decisive" and i == 0:
                probs = {"billing": 0.0, "technical": 1.0, "sales": 0.0, "account": 0.0}
            answers[qid] = {"choice": "billing", "probabilities": probs}
    items = {
        f"{band}{i}": {"gold": "billing", "strength": band}
        for band in rs.BANDS
        for i in range(4)
    }
    return [answers], items


def test_endpoints_retreat_with_evidence_is_scored_from_the_bands():
    passes, items = _endpoint_passes()
    stats = rs.endpoint_stats(passes, items)
    result = {"endpoints": {"choice": stats, "noul": {"n": 40, "exact_0": 0, "exact_1": 0,
                                                      "min": 0.02, "max": 0.97}}}
    verdicts = rs.verdicts(result, 0.247)
    assert verdicts["E2_endpoints_retreat_with_evidence"]["verdict"] == "PROVEN"
    assert verdicts["E1_endpoints_are_per_primitive"]["verdict"] == "PROVEN"


def test_a_noul_at_an_endpoint_refutes_the_per_primitive_claim():
    passes, items = _endpoint_passes()
    result = {"endpoints": {"choice": rs.endpoint_stats(passes, items),
                            "noul": {"n": 40, "exact_0": 1, "exact_1": 0,
                                     "min": 0.0, "max": 0.97}}}
    verdicts = rs.verdicts(result, 0.247)
    assert verdicts["E1_endpoints_are_per_primitive"]["verdict"] == "REFUTED"


def test_one_zero_on_a_correct_option_refutes_e3():
    """The caveat that would move from theoretical to observed."""
    passes, items = _endpoint_passes(zero_on_gold=True)
    stats = rs.endpoint_stats(passes, items)
    assert stats["zeros_on_correct_option"]
    result = {"endpoints": {"choice": stats, "noul": {"n": 4, "exact_0": 0, "exact_1": 0}}}
    assert rs.verdicts(result, 0.247)["E3_no_endpoint_on_a_correct_option"]["verdict"] == "REFUTED"


def test_missing_probes_are_unverifiable():
    out = rs.verdicts({}, 0.247)
    assert set(out) == set(ex.PREREGISTERED)
    assert {b["verdict"] for b in out.values()} == {"UNVERIFIABLE"}


def test_the_runner_and_the_analysis_agree_on_the_hypotheses():
    assert set(ex.PREREGISTERED) == set(rs.verdicts({}, 0.247))


def test_limit_keeps_every_band_represented():
    """A prefix limit emptied the ambiguous band and E2 compares bands."""
    got = ex.stratified(items_mod.generate(), 30)
    assert len(got) == 30
    assert {i["strength"] for i in got} == set(items_mod.BANDS)


def test_limit_is_a_noop_when_it_exceeds_the_set():
    every = items_mod.generate()
    assert ex.stratified(every, None) == every
    assert ex.stratified(every, 999) == every


def test_an_empty_band_is_unverifiable_not_proven():
    """Zero endpoints in a band with zero answers is missing data, not evidence."""
    passes, items = _endpoint_passes()
    stats = rs.endpoint_stats(passes, {k: v for k, v in items.items()
                                       if v["strength"] != "ambiguous"})
    result = {"endpoints": {"choice": stats,
                            "noul": {"n": 4, "exact_0": 0, "exact_1": 0}}}
    block = rs.verdicts(result, 0.247)["E2_endpoints_retreat_with_evidence"]
    assert block["verdict"] == "UNVERIFIABLE"
    assert "ambiguous" in block["why"]
