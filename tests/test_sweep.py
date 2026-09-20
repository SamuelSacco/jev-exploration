"""Tests for the external-sweep audit and the structural probes."""
import json
import os

import pytest

from analysis.sweep import audit
from lab import probe_structure as ps

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------------ sweep audit


def test_claims_file_carries_what_an_audit_needs():
    with open(os.path.join(HERE, "analysis", "sweep", "claims.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["claims"]
    for claim in doc["claims"]:
        assert claim["n"] > 0
        assert claim["distribution"] in audit.DISTRIBUTIONS
        assert claim["sweep_verdict"] and claim["description"]


def test_floor_falls_as_the_distribution_concentrates():
    """The same n reads very differently depending on output shape, which is why
    the audit sweeps rather than assuming one."""
    floors = audit.floors_for(80, trials=200)
    assert floors["spread"]["mean"] > floors["concentrated"]["mean"]
    assert floors["concentrated"]["mean"] > floors["bimodal"]["mean"]


def test_a_small_n_figure_is_not_resolvable():
    """ECE 0.054 at n=80 is noise under one plausible distribution and real
    under another, so it cannot be called evidence either way."""
    label, _ = audit.verdict(0.054, audit.floors_for(80, trials=300))
    assert label in ("UNRESOLVABLE without raw probabilities", "at the floor", "BELOW the floor")
    assert label != "above the floor"


def test_a_large_n_figure_resolves():
    """ECE 0.154 at n=2000 clears the floor under every distribution."""
    label, _ = audit.verdict(0.154, audit.floors_for(2000, trials=300))
    assert label == "above the floor"


def test_missing_ece_is_reported_as_unauditable():
    label, detail = audit.verdict(None, audit.floors_for(100, trials=50))
    assert label == "no ECE reported"
    assert "monotonicity" in detail


def test_local_resolution_settles_the_repo_s_own_claim():
    """Where the raw pairs exist the range collapses to a single answer."""
    resolved = audit.resolve_locally(trials=200)
    if not resolved:
        pytest.skip("negation run not committed")
    block = resolved[0]
    assert block["n"] == 80
    assert block["verdict"] == "at the floor"


# -------------------------------------------------------------- structural probes


def test_every_probe_states_a_prediction_before_running():
    assert set(ps.PREDICTIONS) == {"isolation", "batching", "formulation"}
    for text in ps.PREDICTIONS.values():
        assert len(text) > 40


def test_isolation_conditions_differ_only_in_where_the_code_word_sits():
    payloads = dict((label, (state, qs)) for label, state, qs in ps.isolation_payloads())
    sibling_state, sibling_qs = payloads["in_sibling_question"]
    state_state, state_qs = payloads["in_shared_state"]

    assert ps.CODE_WORD not in sibling_state
    assert ps.CODE_WORD in state_state
    assert ps.CODE_WORD in sibling_qs["carrier"]["instructions"]
    assert ps.CODE_WORD not in state_qs["carrier"]["instructions"]
    # The probe question itself must be identical across conditions, or the
    # comparison measures the wording rather than the placement.
    assert sibling_qs["probe_code"] == state_qs["probe_code"]


def test_absent_control_word_appears_nowhere_in_either_payload():
    for _, state, questions in ps.isolation_payloads():
        assert ps.ABSENT_WORD not in state
        assert ps.ABSENT_WORD not in questions["carrier"]["instructions"]


def test_isolation_scoring_requires_all_four_conditions():
    good = {
        "in_sibling_question": {"probe_code": 0.05, "probe_absent": 0.03},
        "in_shared_state": {"probe_code": 0.91, "probe_absent": 0.04},
    }
    assert ps.score_isolation(good)["prediction_met"] is True

    leaky = {
        "in_sibling_question": {"probe_code": 0.88, "probe_absent": 0.03},
        "in_shared_state": {"probe_code": 0.91, "probe_absent": 0.04},
    }
    assert ps.score_isolation(leaky)["prediction_met"] is False

    # A control that fires means the model says yes to anything; the probe is void.
    noisy = {
        "in_sibling_question": {"probe_code": 0.05, "probe_absent": 0.80},
        "in_shared_state": {"probe_code": 0.91, "probe_absent": 0.04},
    }
    assert ps.score_isolation(noisy)["prediction_met"] is False


def test_batching_recovers_a_known_marginal_cost():
    timings = {1: [1.400], 100: [1.480], 400: [1.720]}
    result = ps.score_batching(timings)
    assert result["marginal_ms_per_question"] == pytest.approx(0.8, abs=0.1)
    assert result["prediction_met"] is True


def test_batching_flags_a_slope_that_breaks_the_prediction():
    timings = {1: [1.4], 100: [3.4], 400: [9.4]}  # 20 ms per question
    assert ps.score_batching(timings)["prediction_met"] is False


def test_batching_payload_ids_are_unique_and_ordered():
    _, questions = ps.batching_payload(400)
    assert len(questions) == 400
    assert sorted(questions) == list(questions)


def test_largest_batch_stays_under_the_request_budget():
    """The documented budget is ~32k tokens."""
    _, questions = ps.batching_payload(400)
    approx_tokens = len(json.dumps(questions)) / 4
    assert approx_tokens < 24000


def test_formulation_compares_the_same_classes_both_ways():
    payloads = dict((label, qs) for label, _, qs in ps.formulation_payloads())
    choice_classes = set(payloads["choice"]["as_choice"]["criteria"])
    noul_classes = {k[3:] for k in payloads["nouls"]}
    assert choice_classes == noul_classes == set(ps.CLASSES)
    assert ps.FORMULATION_GOLD in choice_classes


def test_formulation_scoring_prefers_the_concentrated_form():
    choice = {"billing": 0.88, "technical": 0.04, "sales": 0.04, "other": 0.04}
    nouls = {"billing": 0.95, "technical": 0.48, "sales": 0.55, "other": 0.41}
    result = ps.score_formulation(choice, nouls)
    assert result["choice_distractor_mass"] < result["noul_distractor_mass"]
    assert result["prediction_met"] is True


def test_formulation_scoring_can_fail():
    choice = {"billing": 0.4, "technical": 0.3, "sales": 0.2, "other": 0.1}
    nouls = {"billing": 0.99, "technical": 0.01, "sales": 0.01, "other": 0.01}
    assert ps.score_formulation(choice, nouls)["prediction_met"] is False


def test_dry_run_makes_no_calls(capsys, monkeypatch):
    def explode(*a, **kw):
        raise AssertionError("--dry-run must not call the API")

    monkeypatch.setattr(ps.JevClient, "ask", explode)
    assert ps.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Total calls" in out and "prediction [isolation]" in out
