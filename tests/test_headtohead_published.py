"""Pin the published Jev-vs-local-4B head-to-head figures to committed raw responses.

Run 20260925T015208Z: 33 Jev calls, 1,320 local qwen3:4b calls, zero unparsed.
The verdicts in docs/claims-audit.md rows 25-28 must reproduce from
lab/runs/*-h2h-*.jsonl through analysis/headtohead.py. The local side ran 3
passes per item; the published figures use the per-item mean, matching the
accepted analysis.
"""
import glob
import json
import os
import statistics

from analysis.headtohead import analyse
from lab.exp_headtohead import load_arms

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, "lab", "runs")

ARMS = ["home_turf", "adversarial", "negation", "typed"]


def _read_jev(arm):
    by_qid = {}
    for path in sorted(glob.glob(os.path.join(RUNS, f"*-h2h-{arm}-jev.jsonl"))):
        for line in open(path, encoding="utf-8"):
            d = json.loads(line)
            for qid, ans in d["response"]["answers"].items():
                if ans.get("type") == "choice":
                    by_qid.setdefault(qid, []).append(float(ans["probabilities"].get("yes", 0.0)))
                else:
                    by_qid.setdefault(qid, []).append(float(ans["noul"]))
    # The run repeated items across batches; the published figures use the
    # per-item mean, matching the accepted analysis.
    return {qid: statistics.mean(v) for qid, v in by_qid.items()}


def _read_local(arm):
    by_qid = {}
    for path in sorted(glob.glob(os.path.join(RUNS, f"*-h2h-{arm}-local.jsonl"))):
        for line in open(path, encoding="utf-8"):
            d = json.loads(line)
            by_qid.setdefault(d["id"], []).append(float(d["parsed"]))
    return {qid: statistics.mean(v) for qid, v in by_qid.items()}


def _build_doc():
    arms = load_arms()
    doc = {"arms": {}, "started_at": "20260925T015208Z"}
    for arm in ARMS:
        gold = {item["id"]: bool(item["gold"]) for item in arms[arm]}
        doc["arms"][arm] = {
            "gold": gold,
            "jev": {"probabilities": _read_jev(arm)},
            "local": {"probabilities": _read_local(arm)},
            "n": len(gold),
            "primitive": arms[arm][0]["primitive"],
        }
    return doc


def test_published_accuracies_reproduce_from_committed_raw():
    result = analyse(_build_doc())
    got = {
        arm: (result["arms"][arm]["jev"]["accuracy"], result["arms"][arm]["local"]["accuracy"])
        for arm in ARMS
    }
    assert got["home_turf"] == (1.0, 0.5333), got
    assert got["adversarial"] == (0.8833, 0.4833), got
    assert got["negation"] == (1.0, 0.95), got
    assert got["typed"] == (0.9083, 0.525), got


def test_published_verdicts_reproduce_from_committed_raw():
    result = analyse(_build_doc())
    v = result["verdicts"]
    assert v["H1_jev_clears_the_bar_where_expected"]["verdict"] == "REFUTED"
    assert v["H2_local_wins_home_turf_and_loses_negation"]["verdict"] == "PARTIAL"
    assert v["H3_jev_calibrates_better_everywhere"]["verdict"] == "PARTIAL"
    assert v["H4_choice_beats_noul_on_the_same_items"]["verdict"] == "REFUTED"
    h4 = v["H4_choice_beats_noul_on_the_same_items"]
    assert h4["accuracy_gain"] == 0.025, h4
    assert h4["difference_ci95"][0] <= 0 <= h4["difference_ci95"][1], h4


def test_every_arm_has_both_sides_and_no_unparsed_local():
    result = analyse(_build_doc())
    for arm in ARMS:
        entry = result["arms"][arm]
        assert entry["jev"]["n"] == entry["local"]["n"] == entry["n"], arm
        assert entry["local_unparsed"] == 0, arm
