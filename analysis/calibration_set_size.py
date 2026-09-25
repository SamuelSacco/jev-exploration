"""How many labels does the intercept refit actually need?

    python3 analysis/calibration_set_size.py

No API key and no network. Reads the committed tier responses.

`analysis/CALIBRATION-TRANSFER.md` publishes a recipe: take the Platt slope
fitted anywhere, refit the intercept on about 50 labels from the deployment, and
mean ECE falls 61.7% on held-out items. The 50 was picked as a plausible label
budget, not measured. This sweeps it.

Two things the original measurement did not do, both of which matter:

**Hold out the refit set.** The published figure refits on `test[:50]` and then
scores `apply_map(test, ...)` over all 200 items of the tier, so a quarter of
the evaluation set is the data the intercept was fitted on. That is training
error mixed into a reported result. Here the map is always scored on the items
the refit never saw, and the contaminated number is computed alongside so the
size of the bias is visible rather than argued about.

**Draw the refit set at random, repeatedly.** A prefix is one sample. With
`--draws` repeats per size, the spread across draws is reported, which is what
tells a deployment whether 50 labels is reliably enough or merely enough on
average.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jevlab.calibration import apply_map, fit_platt, fit_platt_intercept  # noqa: E402
from jevlab.stats import ece  # noqa: E402
from lab.tiers.analyse import read_pass  # noqa: E402
from lab.tiers.baselines import TIER_ORDER, load  # noqa: E402

TIER_RUN = "20260918T013027Z"
SIZES = [10, 20, 30, 50, 75, 100]
# Held fixed so the curve is comparable across budgets. An earlier version
# evaluated on whatever the refit did not consume, so the evaluation set
# shrank as the budget grew; ECE is biased upward at small n, and the curve
# turned back up at 150 labels purely because it was being measured on 50
# items. That is the same small-n bias this repo corrects in published
# benchmarks, reproduced inside its own analysis.
EVAL_SIZE = 100
# The label budget analysis/CALIBRATION-TRANSFER.md recommends.
PUBLISHED_BUDGET = 50


def sweep_pair(
    fit_pairs: list,
    test_pairs: list,
    sizes: list,
    draws: int,
    eval_size: int = EVAL_SIZE,
    seed: int = 0,
) -> dict:
    """Slope from `fit_pairs`, intercept refit on k items drawn from `test_pairs`.

    The evaluation set is a fixed-size block the refit never sees, and its size
    does not change with the budget, so ECEs at different budgets are measured
    on the same amount of data and are comparable. `contaminated` repeats the
    published method, scoring on everything including the refit set, so the size
    of that shortcut is visible rather than argued about.
    """
    slope = fit_platt(fit_pairs).a
    rng = random.Random(seed)
    usable = [k for k in sizes if k <= len(test_pairs) - eval_size]
    out = {}
    baselines = []
    for k in usable:
        held, contaminated = [], []
        for _ in range(draws):
            index = list(range(len(test_pairs)))
            rng.shuffle(index)
            evaluate = [test_pairs[i] for i in index[:eval_size]]
            refit = [test_pairs[i] for i in index[eval_size : eval_size + k]]
            mapping = fit_platt_intercept(refit, slope)
            held.append(ece(apply_map(evaluate, mapping)))
            contaminated.append(ece(apply_map(evaluate + refit, mapping)))
            baselines.append(ece(evaluate))
        out[k] = {
            "held_out_ece": round(statistics.mean(held), 4),
            "held_out_sd": round(statistics.pstdev(held), 4) if draws > 1 else 0.0,
            "held_out_worst": round(max(held), 4),
            "contaminated_ece": round(statistics.mean(contaminated), 4),
            "n_eval": eval_size,
        }
    baseline = statistics.mean(baselines) if baselines else ece(test_pairs)
    for k in out:
        out[k]["reduction"] = round((baseline - out[k]["held_out_ece"]) / baseline, 4)
    return {
        "baseline_ece": round(baseline, 4),
        "eval_size": eval_size,
        "slope": round(slope, 4),
        "sizes": out,
    }


def knee(block: dict, tolerance: float = 0.05) -> int:
    """Smallest label budget within `tolerance` of the best mean ECE reached."""
    sizes = block["sizes"]
    if not sizes:
        return 0
    best = min(v["held_out_ece"] for v in sizes.values())
    for k in sorted(sizes):
        if sizes[k]["held_out_ece"] <= best * (1 + tolerance):
            return k
    return max(sizes)


def safe_budget(results: dict, sizes: list) -> int:
    """Smallest budget at which no draw leaves calibration worse than doing nothing.

    The mean flattens early and the tail does not. At a small budget the
    intercept is fitted on too few positives, lands far from where it should,
    and the "correction" moves every probability the wrong way: the worst draws
    here reach four times the uncorrected ECE. A deployment that refits once and
    ships is exposed to the tail, not the mean, so this is the number the recipe
    should quote.
    """
    for k in sorted(sizes):
        rows = [b for b in results.values() if k in b["sizes"]]
        if not rows:
            continue
        if all(b["sizes"][k]["held_out_worst"] < b["baseline_ece"] for b in rows):
            return k
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pass-index", type=int, default=0)
    ap.add_argument("--draws", type=int, default=40, help="random refit sets per size")
    ap.add_argument("--eval-size", type=int, default=EVAL_SIZE,
                    help="held-out items scored at every budget")
    ap.add_argument("--json", help="write the sweep here")
    args = ap.parse_args(argv)

    gold = {r["id"]: r["is_phishing"] for r in load()}
    tiers = {t: read_pass(TIER_RUN, t, args.pass_index, gold) for t in TIER_ORDER}

    results, knees = {}, {}
    for fit_tier in TIER_ORDER:
        for test_tier in TIER_ORDER:
            if fit_tier == test_tier:
                continue
            key = f"{fit_tier}->{test_tier}"
            block = sweep_pair(
                tiers[fit_tier], tiers[test_tier], SIZES, args.draws, args.eval_size
            )
            results[key] = block
            knees[key] = knee(block)

    print(
        f"Intercept refit: ECE on a fixed held-out {args.eval_size} items, "
        f"by label budget\n"
    )
    header = f"  {'transfer':<34} {'before':>7} " + " ".join(f"{k:>7}" for k in SIZES)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for key, block in results.items():
        cells = []
        for k in SIZES:
            cells.append(
                f"{block['sizes'][k]['held_out_ece']:>7.4f}" if k in block["sizes"] else f"{'-':>7}"
            )
        print(f"  {key:<34} {block['baseline_ece']:>7.4f} " + " ".join(cells))

    print("\nSmallest budget within 5% of the best ECE that transfer reaches:\n")
    for key, k in knees.items():
        print(f"  {key:<34} {k:>4} labels")
    typical = statistics.median(knees.values())
    print(f"\n  median across transfers: {typical:.0f} labels")

    # How optimistic is the published method?
    gaps = [
        block["sizes"][PUBLISHED_BUDGET]["contaminated_ece"]
        - block["sizes"][PUBLISHED_BUDGET]["held_out_ece"]
        for block in results.values()
        if PUBLISHED_BUDGET in block["sizes"]
    ]
    mean_held = statistics.mean(
        block["sizes"][PUBLISHED_BUDGET]["held_out_ece"]
        for block in results.values()
        if PUBLISHED_BUDGET in block["sizes"]
    )
    mean_cont = statistics.mean(
        block["sizes"][PUBLISHED_BUDGET]["contaminated_ece"]
        for block in results.values()
        if PUBLISHED_BUDGET in block["sizes"]
    )
    mean_before = statistics.mean(b["baseline_ece"] for b in results.values())
    print(f"\nAt the published budget of {PUBLISHED_BUDGET} labels:\n")
    print(f"  mean ECE before                  {mean_before:.4f}")
    print(f"  after, scored on held-out items  {mean_held:.4f} "
          f"({(mean_before - mean_held) / mean_before:+.1%})")
    print(f"  after, scored the published way  {mean_cont:.4f} "
          f"({(mean_before - mean_cont) / mean_before:+.1%})")
    print(f"  optimism from scoring the refit set   {statistics.mean(gaps):+.4f}")

    worst = max(
        block["sizes"][PUBLISHED_BUDGET]["held_out_worst"]
        for block in results.values()
        if PUBLISHED_BUDGET in block["sizes"]
    )
    print(f"  worst single draw at {PUBLISHED_BUDGET} labels        {worst:.4f}")

    safe = safe_budget(results, SIZES)
    print("\nThe tail, which is what a deployment is exposed to:\n")
    for k in SIZES:
        rows = [b for b in results.values() if k in b["sizes"]]
        if not rows:
            continue
        worst_k = max(b["sizes"][k]["held_out_worst"] for b in rows)
        harmed = sum(
            1 for b in rows if b["sizes"][k]["held_out_worst"] >= b["baseline_ece"]
        )
        ratio = max(
            b["sizes"][k]["held_out_worst"] / b["baseline_ece"] for b in rows
        )
        print(
            f"  {k:>4} labels   worst draw {worst_k:.4f}  "
            f"({ratio:.1f}x the uncorrected ECE)  "
            f"{harmed}/{len(rows)} transfers can end up worse than doing nothing"
        )
    print(
        f"\n  Smallest budget where no draw is worse than doing nothing: {safe} labels."
    )

    result = {
        "pass_index": args.pass_index,
        "draws": args.draws,
        "sizes": SIZES,
        "transfers": results,
        "knees": knees,
        "median_knee": typical,
        "published_budget": PUBLISHED_BUDGET,
        "optimism_at_published_budget": round(statistics.mean(gaps), 4),
        "safe_budget": safe_budget(results, SIZES),
    }
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
