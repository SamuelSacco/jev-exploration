"""Lab harness tests: scoring, baselines and record-keeping, against a fake API."""
import json
import os

import pytest

from jevlab.client import JevResponse
from lab import baselines, run_demos

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def tickets():
    with open(os.path.join(HERE, "lab", "tickets.json"), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def rerank():
    with open(os.path.join(HERE, "lab", "rerank.json"), encoding="utf-8") as fh:
        return json.load(fh)


def perfect_triage(tickets):
    """A response that answers every ticket exactly as labelled."""
    answers = {}
    for t in tickets:
        answers[f"{t['id']}_dept"] = {
            "type": "choice",
            "choice": t["dept"],
            "confidence": 0.95,
            "probabilities": {t["dept"]: 0.95},
        }
        answers[f"{t['id']}_urgent"] = {
            "type": "noul",
            "noul": 0.97 if t["urgent"] else 0.03,
        }
        answers[f"{t['id']}_frustration"] = {
            "type": "score",
            "score": float(t["frustration"]),
            "confidence": 0.9,
        }
    return JevResponse(
        raw={"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 1}},
        elapsed_s=1.5,
        requested_at="2026-09-17T00:00:00Z",
    )


# --------------------------------------------------------------------- payloads


def test_triage_payload_asks_three_questions_per_ticket(tickets):
    state, questions = run_demos.triage_payload(tickets)
    assert len(questions) == len(tickets) * 3
    assert all(t["id"] in state for t in tickets)


def test_rerank_payload_asks_one_noul_per_passage(rerank):
    _, questions = run_demos.rerank_payload(rerank)
    assert len(questions) == len(rerank["passages"])
    assert all(q["type"] == "noul" for q in questions.values())


def test_choice_criteria_include_a_no_match_option(tickets):
    """The docs are explicit that a forced choice with no valid option is a trap."""
    _, questions = run_demos.triage_payload(tickets)
    dept = questions[f"{tickets[0]['id']}_dept"]
    assert "other" in dept["criteria"]


# ---------------------------------------------------------------------- scoring


def test_perfect_answers_score_perfectly(tickets):
    scored = run_demos.score_triage(perfect_triage(tickets), tickets)
    assert scored["dept"]["hits"] == len(tickets)
    assert scored["urgent"]["hits"] == len(tickets)
    assert scored["frustration_mean_abs_error"] == 0.0


def test_every_proportion_carries_an_interval(tickets):
    scored = run_demos.score_triage(perfect_triage(tickets), tickets)
    lo, hi = scored["dept"]["ci95"]
    assert hi == 1.0
    assert lo < 1.0, "12/12 is not certainty; the interval must show that"


def test_a_wrong_department_is_counted_as_wrong(tickets):
    """No post-hoc relabelling: a miss stays a miss."""
    resp = perfect_triage(tickets)
    first = tickets[0]["id"]
    resp.raw["answers"][f"{first}_dept"]["choice"] = "definitely_not_the_label"
    scored = run_demos.score_triage(resp, tickets)
    assert scored["dept"]["hits"] == len(tickets) - 1


def test_rerank_scoring_ranks_by_probability(rerank):
    answers = {
        p["id"]: {"type": "noul", "noul": 0.96 if p["relevant"] else 0.02}
        for p in rerank["passages"]
    }
    resp = JevResponse(raw={"model": "m", "answers": answers}, elapsed_s=1.0)
    scored = run_demos.score_rerank(resp, rerank)
    assert scored["relevance"]["hits"] == len(rerank["passages"])
    assert scored["relevant_in_top4"] == 4
    assert [r["id"] for r in scored["ranking"]][:4] == [
        p["id"] for p in rerank["passages"] if p["relevant"]
    ]


# -------------------------------------------------------------------- baselines


def test_baselines_run_without_a_key_or_network(capsys):
    baselines.main()
    out = capsys.readouterr().out
    assert "word-overlap" in out and "95% CI" in out


def test_rerank_baseline_nearly_matches_jev_on_this_dataset(rerank):
    """The demo's distractors are trivially separable; this is why it proves little."""
    result = run_demos.rerank_baselines(rerank)["word_overlap"]
    assert result["hits"] >= 7, "a keyword heuristic already gets 7/8 here"


def test_baseline_and_jev_intervals_overlap(rerank):
    """The finding that motivated the rewrite, pinned so it cannot regress silently."""
    baseline = run_demos.rerank_baselines(rerank)["word_overlap"]
    jev_lo, _ = run_demos.wilson(8, 8)
    assert baseline["ci95"][1] > jev_lo


# --------------------------------------------------------------------- variance


def test_variance_needs_more_than_one_pass(tickets):
    result = run_demos.variance([perfect_triage(tickets)], ["t1_urgent"], lambda p, q: p.noul(q))
    assert "note" in result


def test_variance_detects_a_label_flip(tickets):
    a = perfect_triage(tickets)
    b = perfect_triage(tickets)
    b.raw["answers"]["t1_urgent"]["noul"] = 0.4  # flips across the 0.5 line
    result = run_demos.variance([a, b], ["t1_urgent", "t2_urgent"], lambda p, q: p.noul(q))
    assert result["label_flip_rate"] == 0.5
    assert result["max_abs_spread"] > 0.5


# ---------------------------------------------------------------- record-keeping


def test_raw_responses_are_recorded_before_scoring(tmp_path, tickets, monkeypatch):
    monkeypatch.setattr(run_demos, "RUNS_DIR", str(tmp_path))
    resp = perfect_triage(tickets)
    run_demos.record("triage", resp, "20260917T000000Z")

    written = list(tmp_path.iterdir())
    assert len(written) == 1
    line = json.loads(written[0].read_text().splitlines()[0])
    assert line["model"] == "jev-1.13.0"
    assert line["response"]["answers"], "the full raw response must be kept"
    assert "elapsed_s" in line and "attempts" in line


def test_repeated_passes_append_rather_than_overwrite(tmp_path, tickets, monkeypatch):
    monkeypatch.setattr(run_demos, "RUNS_DIR", str(tmp_path))
    for _ in range(3):
        run_demos.record("triage", perfect_triage(tickets), "20260917T000000Z")
    written = list(tmp_path.iterdir())[0]
    assert len(written.read_text().strip().splitlines()) == 3


def test_calibration_block_reports_the_floor(tickets):
    scored = run_demos.score_triage(perfect_triage(tickets), tickets)
    block = run_demos.calibration_block(scored["urgent_pairs"], "urgency")
    assert set(block) >= {"ece", "noise_floor_mean", "ratio_to_floor", "informative"}
    assert block["n"] == len(tickets)


def test_dry_run_makes_no_calls(capsys, monkeypatch):
    def explode(*a, **kw):
        raise AssertionError("--dry-run must not call the API")

    monkeypatch.setattr(run_demos.JevClient, "ask", explode)
    assert run_demos.main(["--dry-run", "--only", "rerank"]) == 0
    assert "questions" in capsys.readouterr().out
