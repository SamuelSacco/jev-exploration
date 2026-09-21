"""Tests for the Jev vs local-4B battery.

Neither side can be called here, so what is tested is everything that can go
wrong silently: the parser that turns a small model's prose into a number, the
arm construction, and the verdict logic in both directions.
"""
import json

import pytest

from analysis import headtohead as hh
from lab import exp_headtohead as ex


# ------------------------------------------------------------------- the parser


@pytest.mark.parametrize(
    "reply,expected",
    [
        ("0.82", 0.82),
        ("  0.9  ", 0.9),
        (".75", 0.75),
        ("1", 1.0),
        ("0", 0.0),
        ("Probability: 0.73", 0.73),
        ("probability: 85%", 0.85),
        ("85%", 0.85),
        ("yes (probability 95%)", 0.95),
        ("I think it is 0.4.", 0.4),
        ("p=0.07", 0.07),
        ("Reasoning follows.\n\n0.68", 0.68),
        ("<think>maybe 0.99 no wait</think> 0.12", 0.12),
        ("Between 0.3 and 0.7 I would say 0.55", 0.55),
    ],
)
def test_parser_reads_the_shapes_a_small_model_emits(reply, expected):
    assert ex.parse_probability(reply) == pytest.approx(expected)


@pytest.mark.parametrize("reply", ["", "The answer is yes", "1.5", "42", None, "maybe"])
def test_parser_returns_none_rather_than_guessing(reply):
    """A silent 0.5 would read as calibrated uncertainty and be a parser bug."""
    assert ex.parse_probability(reply) is None


def test_thinking_tags_are_stripped_before_the_answer_is_read():
    assert ex.parse_probability("<think>0.01 0.02 0.03</think>\n0.91") == 0.91


def test_the_last_number_wins_because_models_conclude_at_the_end():
    assert ex.parse_probability("First 0.1, then 0.2, finally 0.9") == 0.9


# ---------------------------------------------------------------------- the arms


def test_four_arms_are_built_from_committed_data():
    arms = ex.load_arms()
    assert set(arms) == set(ex.ARMS)
    for name, items in arms.items():
        assert items, name
        for item in items:
            assert isinstance(item["gold"], bool)
            assert item["question"] and item["text"]
            assert set(item["criteria"]) == {"true", "false"}


def test_typed_and_adversarial_share_their_items_exactly():
    """The only difference between the arms must be the primitive."""
    arms = ex.load_arms()
    assert [i["id"] for i in arms["typed"]] == [i["id"] for i in arms["adversarial"]]
    assert [i["text"] for i in arms["typed"]] == [i["text"] for i in arms["adversarial"]]
    assert [i["gold"] for i in arms["typed"]] == [i["gold"] for i in arms["adversarial"]]
    assert {i["primitive"] for i in arms["typed"]} == {"choice"}
    assert {i["primitive"] for i in arms["adversarial"]} == {"noul"}


def test_choice_criteria_is_a_dict_not_a_list():
    """A list of options is rejected with 422."""
    arms = ex.load_arms(limit=2)
    _, questions = ex.build_jev(arms["typed"])
    for question in questions.values():
        assert question["type"] == "choice"
        assert isinstance(question["criteria"], dict)
        assert set(question["criteria"]) == {"yes", "no"}


def test_reading_a_choice_answer_takes_the_yes_probability():
    from jevlab.transport import Reply

    item = {"id": "q1", "primitive": "choice"}
    reply = Reply(raw={"answers": {"q1": {
        "type": "choice", "choice": "yes",
        "probabilities": {"yes": 0.77, "no": 0.23}, "confidence": 0.9,
    }}})
    assert ex.read_jev(reply, item) == 0.77


def test_reading_a_missing_answer_is_none_not_a_default():
    from jevlab.transport import Reply

    reply = Reply(raw={"answers": {}})
    assert ex.read_jev(reply, {"id": "nope", "primitive": "noul"}) is None


def test_dry_run_needs_no_transport_of_either_kind(capsys, monkeypatch):
    monkeypatch.delenv("JEV_LOCAL_TRANSPORT", raising=False)
    assert ex.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Jev calls: 33" in out
    assert "H4_choice_beats_noul_on_the_same_items" in out


def test_a_local_transport_is_required_rather_than_defaulted(monkeypatch):
    """This repo must hold no code that can reach a non-Jev endpoint."""
    from jevlab import transport

    monkeypatch.delenv(transport.LOCAL_ENV_VAR, raising=False)
    with pytest.raises(RuntimeError, match="JEV_LOCAL_TRANSPORT"):
        transport.resolve_local_sender()


# ------------------------------------------------------------------- the memo


def _arm(jev_acc, local_acc, jev_ratio, local_ratio, bar=0.5, n=100):
    return {
        "n": n, "primitive": "noul", "lexical_bar": bar,
        "jev": {"n": n, "accuracy": jev_acc, "ci95": [jev_acc - 0.05, jev_acc + 0.05],
                "ece": 0.05, "floor": 0.02, "ratio": jev_ratio},
        "local": {"n": n, "accuracy": local_acc, "ci95": [local_acc - 0.05, local_acc + 0.05],
                  "ece": 0.05, "floor": 0.02, "ratio": local_ratio},
        "local_unparsed": 0, "local_latency_p50_s": 1.0,
    }


def test_h1_is_refuted_when_jev_clears_the_bar_on_the_adversarial_arm():
    arms = {
        "home_turf": _arm(0.90, 0.95, 1.5, 3.0, bar=0.80),
        "adversarial": _arm(0.95, 0.60, 1.5, 3.0, bar=0.70),
        "negation": _arm(0.90, 0.60, 1.5, 3.0, bar=0.50),
    }
    assert hh.verdicts(arms)["H1_jev_clears_the_bar_where_expected"]["verdict"] == "REFUTED"


def test_h1_is_proven_on_the_expected_pattern():
    arms = {
        "home_turf": _arm(0.90, 0.95, 1.5, 3.0, bar=0.80),
        "adversarial": _arm(0.68, 0.60, 1.5, 3.0, bar=0.70),
        "negation": _arm(0.90, 0.60, 1.5, 3.0, bar=0.50),
    }
    assert hh.verdicts(arms)["H1_jev_clears_the_bar_where_expected"]["verdict"] == "PROVEN"


def test_h2_is_partial_when_only_one_half_holds():
    arms = {
        "home_turf": _arm(0.80, 0.90, 1.5, 3.0),
        "negation": _arm(0.60, 0.70, 1.5, 3.0),
    }
    assert hh.verdicts(arms)["H2_local_wins_home_turf_and_loses_negation"]["verdict"] == "PARTIAL"


def test_h3_is_refuted_when_the_local_model_calibrates_better_everywhere():
    arms = {a: _arm(0.8, 0.8, 3.0, 1.2) for a in hh.ARMS}
    block = hh.verdicts(arms)["H3_jev_calibrates_better_everywhere"]
    assert block["verdict"] == "REFUTED"


def test_h3_is_partial_when_it_holds_on_some_arms_only():
    arms = {a: _arm(0.8, 0.8, 1.2, 3.0) for a in hh.ARMS}
    arms["negation"] = _arm(0.8, 0.8, 3.0, 1.2)
    assert hh.verdicts(arms)["H3_jev_calibrates_better_everywhere"]["verdict"] == "PARTIAL"


def test_h4_is_refuted_when_the_difference_interval_covers_zero():
    arms = {
        "adversarial": _arm(0.70, 0.60, 1.5, 3.0),
        "typed": _arm(0.74, 0.60, 1.5, 3.0),
    }
    arms["typed"]["vs_adversarial_ci"] = [-0.02, 0.10]
    assert hh.verdicts(arms)["H4_choice_beats_noul_on_the_same_items"]["verdict"] == "REFUTED"


def test_h4_is_proven_when_the_interval_clears_zero():
    arms = {
        "adversarial": _arm(0.70, 0.60, 1.5, 3.0),
        "typed": _arm(0.82, 0.60, 1.5, 3.0),
    }
    arms["typed"]["vs_adversarial_ci"] = [0.04, 0.20]
    assert hh.verdicts(arms)["H4_choice_beats_noul_on_the_same_items"]["verdict"] == "PROVEN"


def test_missing_sides_are_unverifiable_not_a_verdict():
    out = hh.verdicts({})
    assert {b["verdict"] for b in out.values()} == {"UNVERIFIABLE"}


def test_difference_ci_is_on_the_difference_not_on_two_intervals():
    """Paired: the same items on both sides, so the interval is on the delta."""
    good = [(0.9, True)] * 50 + [(0.1, False)] * 50
    bad = [(0.1, True)] * 50 + [(0.9, False)] * 50
    lo, hi = hh.difference_ci(good, bad)
    assert lo > 0.9 and hi <= 1.0
    lo, hi = hh.difference_ci(good, good)
    assert lo == 0.0 and hi == 0.0


def test_analyse_and_memo_run_end_to_end(tmp_path):
    arms = ex.load_arms(limit=20)
    doc = {"started_at": "t", "transport_jev": "j", "transport_local": "l",
           "preregistered": ex.PREREGISTERED, "arms": {}}
    for name, items in arms.items():
        gold = {i["id"]: i["gold"] for i in items}
        doc["arms"][name] = {
            "n": len(items), "primitive": items[0]["primitive"], "gold": gold,
            "jev": {"probabilities": {k: (0.8 if g else 0.2) for k, g in gold.items()}},
            "local": {"probabilities": {k: (0.6 if g else 0.4) for k, g in gold.items()},
                      "unparsed": [], "latency_p50_s": 1.0},
        }
    result = hh.analyse(doc)
    assert set(result["arms"]) == set(ex.ARMS)
    for name in ex.ARMS:
        assert result["arms"][name]["jev"]["accuracy"] == 1.0
    text = hh.memo(result)
    assert "verdict memo" in text and "H4_choice_beats_noul_on_the_same_items" in text
    out = tmp_path / "answers.json"
    out.write_text(json.dumps(doc), encoding="utf-8")
    assert hh.main(["--answers", str(out), "--memo", str(tmp_path / "memo.md")]) == 0
    assert (tmp_path / "memo.md").read_text(encoding="utf-8").startswith("# Jev vs local 4B")


def test_runner_reports_every_hypothesis_the_analysis_scores():
    assert set(ex.PREREGISTERED) == set(hh.verdicts({}))
