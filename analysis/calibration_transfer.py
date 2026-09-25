"""Does a calibration map fitted on one slice of Jev transfer to another?

    python3 analysis/calibration_transfer.py

No API key: everything reads the committed raw responses.

The gradient experiment found that Jev's miscalibration curve barely moves with
difficulty. If that is right, a correction fitted on one tier should work on the
others, and Jev becomes a monotone score you calibrate yourself rather than a
probability you have to trust.

Every number here is out-of-sample. The map is never fitted and scored on the
same data, because a monotone fit can drive in-sample ECE to zero and tell you
nothing (isotonic does exactly that on the sanity check in the tests).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

from jevlab.calibration import (  # noqa: E402
    FITTERS,
    apply_map,
    evaluate_transfer,
    fit_platt,
    fit_platt_intercept,
)
from analysis.calibration_set_size import EVAL_SIZE, SIZES, sweep_pair  # noqa: E402
from jevlab.stats import ece, reliability  # noqa: E402
from lab.run_demos import negation_items  # noqa: E402
from lab.tiers.analyse import read_pass  # noqa: E402
from lab.tiers.baselines import TIER_ORDER, load  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, "lab", "runs")
TIER_RUN = "20260918T013027Z"
NEGATION_RUN = "20260918T014148Z-negation.jsonl"
CALIBRATION_LABELS = 50


def negation_pairs() -> list:
    path = os.path.join(RUNS, NEGATION_RUN)
    if not os.path.exists(path):
        return []
    with open(os.path.join(ROOT, "lab", "negation.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    gold = {i: g for i, _, _, g in negation_items(doc)}
    with open(path, encoding="utf-8") as fh:
        record = json.loads(fh.readline())
    return [
        (a["noul"], gold[q])
        for q, a in record["response"]["answers"].items()
        if q in gold
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--method", choices=sorted(FITTERS), default="platt")
    ap.add_argument("--pass-index", type=int, default=0)
    args = ap.parse_args(argv)

    gold = {r["id"]: r["is_phishing"] for r in load()}
    tiers = {t: read_pass(TIER_RUN, t, args.pass_index, gold) for t in TIER_ORDER}
    negation = negation_pairs()

    print(f"method: {args.method}, tier run {TIER_RUN}, pass {args.pass_index + 1}\n")
    print("Fitted on one tier, scored on another (all out-of-sample).")
    print("ECE on the test tier, before -> after the map:\n")
    header = f"{'fit on':<16} " + " ".join(f"{t[:2]:>14}" for t in TIER_ORDER)
    print(header)
    print("-" * len(header))
    reductions = []
    for fit_tier in TIER_ORDER:
        cells = []
        for test_tier in TIER_ORDER:
            if fit_tier == test_tier:
                cells.append(f"{'—':>14}")
                continue
            r = evaluate_transfer(
                tiers[fit_tier], tiers[test_tier], method=args.method
            )
            reductions.append(r["ece_reduction"])
            cells.append(f"{r['ece_before']:.3f}->{r['ece_after']:.3f}")
        print(f"{fit_tier:<16} " + " ".join(f"{c:>14}" for c in cells))

    mean_reduction = sum(reductions) / len(reductions)
    print(
        f"\nMean ECE reduction across the 12 out-of-sample transfers: "
        f"{mean_reduction:.1%}"
    )
    worst = min(reductions)
    print(f"Worst single transfer: {worst:.1%}")

    print("\nSlope-only transfer: slope from the fit tier, intercept refit on 50")
    print("labels per transfer (40 random refit sets), scored on a fixed 100-item")
    print("held-out block the refit never saw. Same machinery as")
    print("analysis/calibration_set_size.py, so this row and the sweep agree by")
    print("construction. The old version of this section scored the refit items")
    print("too and reported 74%; see 'Two corrections' in")
    print("analysis/CALIBRATION-TRANSFER.md.\n")
    print(header)
    print("-" * len(header))
    before_scores, slope_scores, worst_cases = [], [], []
    for fit_tier in TIER_ORDER:
        cells = []
        for test_tier in TIER_ORDER:
            if fit_tier == test_tier:
                cells.append(f"{'—':>14}")
                continue
            block = sweep_pair(
                tiers[fit_tier],
                tiers[test_tier],
                SIZES,
                40,
                EVAL_SIZE,
            )
            s = block["sizes"][CALIBRATION_LABELS]
            before_scores.append(block["baseline_ece"])
            slope_scores.append(s["held_out_ece"])
            worst_cases.append(s["held_out_worst"])
            cells.append(f"{block['baseline_ece']:.3f}->{s['held_out_ece']:.3f}")
        print(f"{fit_tier:<16} " + " ".join(f"{c:>14}" for c in cells))

    mean_before = sum(before_scores) / len(before_scores)
    mean_slope = sum(slope_scores) / len(slope_scores)
    print(
        f"\n  mean ECE  before {mean_before:.4f}   "
        f"slope-only {mean_slope:.4f} ({(mean_before - mean_slope) / mean_before:+.1%})"
    )
    print(f"  worst single draw  slope-only {max(worst_cases):.4f}")
    print("\nFitted slope and intercept per tier (the slope is what transfers):")
    for tier in TIER_ORDER:
        m = fit_platt(tiers[tier])
        print(f"  {tier:<16} a={m.a:.2f}  b={m.b:+.2f}")

    print("\nAccuracy is unchanged by construction (the maps are monotone):")
    r = evaluate_transfer(tiers["t1_trivial"], tiers["t4_adversarial"], method=args.method)
    print(
        f"  t1 -> t4   accuracy {r['accuracy_before']:.3f} -> {r['accuracy_after']:.3f}, "
        f"Brier {r['brier_before']:.4f} -> {r['brier_after']:.4f}"
    )

    if negation:
        print("\nCross-task, still within email: fitted on a tier, scored on the")
        print("negation probe (a different question wording and a different construction).")
        for fit_tier in TIER_ORDER:
            r = evaluate_transfer(tiers[fit_tier], negation, method=args.method)
            print(
                f"  fit {fit_tier:<16} negation ECE {r['ece_before']:.3f} -> "
                f"{r['ece_after']:.3f}  ({r['ece_reduction']:+.1%})"
            )

    print("\nThe map fitted on t1, applied to t4:")
    mapping = FITTERS[args.method](tiers["t1_trivial"])
    print(f"  {mapping.description}")
    mapped = apply_map(tiers["t4_adversarial"], mapping)
    print(f"  {'bin':>10} {'n':>4} {'mean p':>8} {'hit':>6} {'gap':>7}")
    for b in reliability(mapped):
        print(
            f"  {b.lo:.1f}-{b.hi:.1f} {b.count:>4} {b.mean_p:>8.3f} "
            f"{b.hit_rate:>6.3f} {b.gap:>+7.3f}"
        )
    print(f"  ECE {ece(tiers['t4_adversarial']):.4f} -> {ece(mapped):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
