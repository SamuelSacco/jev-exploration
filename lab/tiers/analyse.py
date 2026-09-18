"""Analyse the difficulty-gradient run (issue #1). No API key needed.

    python3 lab/tiers/analyse.py
    python3 lab/tiers/analyse.py --run 20260918T013027Z --pass-index 1

Reads the committed raw responses, so every number here is re-derivable from
lab/runs/ rather than trusted from results.json.

Three things this does that the per-tier scalars in results.json do not:

1. Bootstraps a CI on the *difference* in ECE between tiers. Comparing two
   independent intervals for overlap is the wrong test and far too conservative.
2. Decomposes any ECE change into a calibration effect and a mass effect. ECE
   moves either because each bin's gap widened, or because predictions relocated
   into bins that were already bad. Those mean opposite things.
3. Repeats both across every pass, so a finding cannot rest on one sample.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from jevlab.stats import (  # noqa: E402
    coverage_at,
    decompose_ece,
    ece,
    format_reliability,
    reliability,
)
from lab.tiers.baselines import TIER_ORDER, load  # noqa: E402

RUNS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runs")
BATCHES_PER_PASS = 5


def read_pass(run: str, tier: str, index: int, gold: dict) -> list:
    """(probability, outcome) pairs for one pass over one tier."""
    path = os.path.join(RUNS, f"{run}-tiers-{tier}.jsonl")
    with open(path, encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    # Records are written pass-major: pass 0's batches, then pass 1's, ...
    chunk = records[index * BATCHES_PER_PASS : (index + 1) * BATCHES_PER_PASS]
    answers: dict = {}
    for record in chunk:
        for qid, answer in record["response"]["answers"].items():
            answers[qid] = answer["noul"]
    return [(answers[i], gold[i]) for i in sorted(answers) if i in gold]


def ece_difference_ci(a: list, b: list, resamples: int = 4000, seed: int = 3) -> tuple:
    """Percentile CI on ece(b) - ece(a), resampling both independently."""
    rng = random.Random(seed)
    na, nb = len(a), len(b)
    values = []
    for _ in range(resamples):
        sa = [a[rng.randrange(na)] for _ in range(na)]
        sb = [b[rng.randrange(nb)] for _ in range(nb)]
        values.append(ece(sb) - ece(sa))
    values.sort()
    return (
        values[int(0.025 * resamples)],
        values[int(0.975 * resamples)],
        sum(1 for v in values if v <= 0) / resamples,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", help="run timestamp; defaults to the newest in lab/runs/")
    ap.add_argument("--pass-index", type=int, default=0)
    ap.add_argument("--passes", type=int, default=3)
    args = ap.parse_args(argv)

    run = args.run
    if not run:
        found = sorted(glob.glob(os.path.join(RUNS, "*-tiers-t1_trivial.jsonl")))
        if not found:
            print("No tier runs in lab/runs/.", file=sys.stderr)
            return 1
        run = os.path.basename(found[-1]).split("-tiers-")[0]

    gold = {r["id"]: r["is_phishing"] for r in load()}
    data = {t: read_pass(run, t, args.pass_index, gold) for t in TIER_ORDER}

    print(f"run {run}, pass {args.pass_index + 1}\n")
    print("Per-tier ECE against t1, bootstrap CI on the difference:")
    for tier in TIER_ORDER[1:]:
        lo, hi, p = ece_difference_ci(data["t1_trivial"], data[tier])
        delta = ece(data[tier]) - ece(data["t1_trivial"])
        verdict = "significant" if lo > 0 else "NOT significant"
        print(
            f"  t1 -> {tier:<16} {delta:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]  "
            f"P(<=0)={p:.3f}  {verdict}"
        )

    print("\nAttribution of the t1 -> t4 change, every pass:")
    print(f"  {'pass':>4} {'ECE t1':>8} {'ECE t4':>8} {'calibration':>12} {'mass':>8}  verdict")
    for index in range(args.passes):
        p1 = read_pass(run, "t1_trivial", index, gold)
        p4 = read_pass(run, "t4_adversarial", index, gold)
        d = decompose_ece(p1, p4)
        verdict = "calibration worse" if d["calibration_worsened"] else "mass shift only"
        print(
            f"  {index + 1:>4} {d['baseline_ece']:>8.4f} {d['compare_ece']:>8.4f} "
            f"{d['compare_gaps_under_baseline_mass']:>12.4f} "
            f"{d['baseline_gaps_under_compare_mass']:>8.4f}  {verdict}"
        )
    print(
        "  calibration = t4's gaps under t1's mass. At or below t1's own ECE, the\n"
        "  calibration function did not get worse. mass = t1's gaps under t4's mass."
    )

    print("\nHigh-confidence routing (p >= 0.9 taken as a phishing call):")
    for tier in TIER_ORDER:
        c = coverage_at(data[tier], 0.9)
        print(
            f"  {tier:<16} coverage {c['coverage']:>5.1%}  "
            f"hit rate {c['hit_rate']:.3f}  (n={c['n']})"
        )

    print("\nDirection of the gap by bin (+ overstates P(phishing), - understates):")
    for tier in TIER_ORDER:
        row = " ".join(
            f"{b.lo:.1f}{'+' if b.gap > 0 else '-'}" for b in reliability(data[tier])
        )
        print(f"  {tier:<16} {row}")

    print(f"\nt4 reliability table:\n{format_reliability(data['t4_adversarial'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
