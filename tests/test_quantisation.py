"""Tests for the numeric-resolution audit of the committed raw responses."""
import json

import pytest

from analysis import quantisation as q


@pytest.fixture(scope="module")
def bodies():
    return q.responses()


@pytest.fixture(scope="module")
def values(bodies):
    return q.numbers(bodies)


def test_reads_the_committed_responses(bodies):
    assert len(bodies) >= 60
    for source, body in bodies:
        assert source.endswith(".jsonl")
        assert "answers" in body and body["answers"]


def test_direct_responses_carry_no_rounding_metadata(bodies):
    """The Gateway declares its rounding; the direct API does not.

    If TypeSafe ever adds the block, this fails and the answer recorded in the
    ledger for issue #10 needs revisiting.

    Underscore-prefixed keys are the operator's own transport metadata
    (observed round trip, which transport ran it), not API response fields.
    """
    meta = q.metadata_audit(bodies)
    api_keys = {k for k in meta["top_level_keys"] if not k.startswith("_")}
    assert api_keys == {"answers", "model", "usage"}
    assert meta["declares_rounding"] is False
    assert meta["rounding_keys_found"] == []


def test_every_returned_number_sits_on_the_hundredths_grid(values):
    assert len(values) > 3000
    assert q.grid_audit(values)["off_grid"] == 0


def test_the_grid_check_is_not_vacuous(values):
    """A value that is genuinely off the grid has to be caught."""
    planted = list(values) + [("planted.jsonl", "noul", "noul", 0.123)]
    stray = q.off_grid(planted)
    assert [row[3] for row in stray] == [0.123]


def test_representation_slack_does_not_hide_a_real_third_decimal():
    """0.8200000000000001 is on the grid; 0.821 is not."""
    near = [("x", "choice", "probabilities", 0.8200000000000001)]
    far = [("x", "choice", "probabilities", 0.821)]
    assert q.off_grid(near) == []
    assert len(q.off_grid(far)) == 1


def test_quantised_distributions_almost_sum_to_one(bodies):
    """The rounding residual is not always absorbed.

    842 of 843 committed distributions sum to exactly 1. One jev-1.13.0 choice
    vector from the 2026-09-24 shape probe sums to 0.99 (rs038: 0.01 + 0.81 +
    0.17 + 0.0), so the grid holds but the sum does not always. If a second
    sub-1.0 vector appears, the "one entry absorbs the residual" story in the
    claims audit needs rewriting, not relaxing.
    """
    sums = q.distribution_sums(bodies)
    assert sums["distributions"] > 0
    assert set(sums["sums"]) <= {0.99, 1.0}
    assert sums["sums"].get(1.0, 0) / sums["distributions"] >= 0.99


def test_choice_and_score_reach_the_endpoints(values):
    ends = q.endpoint_audit(values)
    assert ends["choice.probabilities"]["exact_0"] > 0
    assert ends["choice.probabilities"]["exact_1"] > 0
    assert ends["score.probabilities"]["exact_0"] > 0


def test_noul_never_reached_an_endpoint(values):
    """The observation behind the ledger's per-primitive caveat.

    Noul is the primitive every calibration result in this repo is measured on,
    and a Platt or temperature correction is undefined at an exact 0 or 1. If a
    future run returns one, this fails and the caveat has to be rewritten.
    """
    ends = q.endpoint_audit(values)
    noul = ends["noul.noul"]
    assert noul["n"] >= 2000
    assert noul["exact_0"] == 0
    assert noul["exact_1"] == 0
    assert noul["min"] >= 0.01
    assert noul["max"] <= 0.99


def test_main_runs_and_writes_json(tmp_path, capsys):
    out = tmp_path / "quantisation.json"
    assert q.main(["--json", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["metadata"]["declares_rounding"] is False
    assert doc["grid"]["off_grid"] == 0
    assert doc["noul_clamp"]["noul_endpoint_rate_upper_95"] < 0.01
    assert "0.01 grid" in capsys.readouterr().out
