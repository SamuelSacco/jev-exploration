"""Audit externally reported Jev calibration figures against their noise floors.

    python3 analysis/sweep/audit.py

No API key. Reads analysis/sweep/claims.json.

An ECE figure cannot be read without the floor it sits on, and that floor depends
on the sample size *and* on how the model's probabilities are distributed. Jev
concentrates output near 0 and 1, which lowers the floor; a study reporting only
n and ECE has not supplied enough to interpret its own number.

This sweeps the floor across three plausible output distributions rather than
assuming one, and reports the verdict as a range. Where the range spans
"uninformative" to "real", the claim is unresolvable without the raw
probabilities, and the honest verdict is that the study has not established
calibration either way.

Distributions:

  spread        probabilities anywhere in [0, 1]
  concentrated  45% near 0, 45% near 1, 10% spread through the middle
  bimodal       50/50 near 0 and near 1, nothing in between

"bimodal" is the sweep's own description of Jev output ("bins 0.1-0.4 were
EMPTY"). It gives the *lowest* floor and therefore the most generous reading.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from jevlab.stats import ece_noise_floor  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

DISTRIBUTIONS = ("spread", "concentrated", "bimodal")


def sample_probs(kind: str, n: int, rng: random.Random) -> list:
    out = []
    for _ in range(n):
        if kind == "spread":
            out.append(rng.random())
        elif kind == "bimodal":
            out.append(
                rng.uniform(0.0, 0.10) if rng.random() < 0.5 else rng.uniform(0.90, 1.0)
            )
        else:  # concentrated
            r = rng.random()
            out.append(
                rng.uniform(0.0, 0.10)
                if r < 0.45
                else (rng.uniform(0.90, 1.0) if r < 0.90 else rng.uniform(0.10, 0.90))
            )
    return out


def floors_for(n: int, trials: int, seed: int = 0) -> dict:
    rng = random.Random(seed)
    return {
        kind: ece_noise_floor(sample_probs(kind, n, rng), trials=trials)
        for kind in DISTRIBUTIONS
    }


def verdict(reported: float | None, floors: dict) -> tuple:
    """Return (label, detail). Ranges across the plausible distributions."""
    if reported is None:
        return ("no ECE reported", "cannot be audited; bin monotonicity is not an ECE")
    ratios = {k: reported / f["mean"] for k, f in floors.items() if f["mean"]}
    lo_kind = min(ratios, key=ratios.get)
    hi_kind = max(ratios, key=ratios.get)
    lo, hi = ratios[lo_kind], ratios[hi_kind]
    detail = f"{lo:.2f}x ({lo_kind}) to {hi:.2f}x ({hi_kind})"
    if hi <= 1.0:
        return ("BELOW the floor", detail)
    if hi < 2.0:
        return ("at the floor", detail)
    if lo >= 2.0:
        return ("above the floor", detail)
    return ("UNRESOLVABLE without raw probabilities", detail)


def resolve_locally(trials: int) -> list:
    """Recompute the claims whose raw responses are committed in this repo.

    Only B3 qualifies: it is this repo's own negation probe, and the sweep
    carried it forward as a baseline finding.
    """
    try:
        from jevlab.stats import ece, ece_with_floor
        from analysis.calibration_transfer import negation_pairs
    except Exception:
        return []
    pairs = negation_pairs()
    if not pairs:
        return []
    block = ece_with_floor(pairs, trials=trials)
    ratio = block["ratio"]
    return [
        {
            "id": "B3-negation",
            "n": len(pairs),
            "ece": ece(pairs),
            "floor": block["floor_mean"],
            "ratio": ratio,
            "verdict": "at the floor" if not block["informative"] else "above the floor",
        }
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--claims", default=os.path.join(HERE, "claims.json"))
    ap.add_argument("--trials", type=int, default=600)
    ap.add_argument("--json", help="write the audit result here")
    args = ap.parse_args(argv)

    with open(args.claims, encoding="utf-8") as fh:
        doc = json.load(fh)

    print(f"source: {doc['source']}\n")
    header = f"{'claim':<24} {'n':>6} {'ECE':>7} {'ratio to floor':>34}  verdict"
    print(header)
    print("-" * len(header))

    results = []
    for claim in doc["claims"]:
        floors = floors_for(claim["n"], args.trials)
        label, detail = verdict(claim.get("reported_ece"), floors)
        ece_txt = (
            f"{claim['reported_ece']:.3f}" if claim.get("reported_ece") else "none"
        )
        print(f"{claim['id']:<24} {claim['n']:>6} {ece_txt:>7} {detail:>34}  {label}")
        results.append(
            {
                "id": claim["id"],
                "n": claim["n"],
                "reported_ece": claim.get("reported_ece"),
                "sweep_verdict": claim["sweep_verdict"],
                "floor_by_distribution": {
                    k: round(v["mean"], 4) for k, v in floors.items()
                },
                "audit_verdict": label,
                "ratio_range": detail,
            }
        )

    print("\nFloors by sample size and output distribution:")
    seen = set()
    print(f"  {'n':>6} " + " ".join(f"{k:>14}" for k in DISTRIBUTIONS))
    for claim in doc["claims"]:
        if claim["n"] in seen:
            continue
        seen.add(claim["n"])
        floors = floors_for(claim["n"], args.trials)
        print(
            f"  {claim['n']:>6} "
            + " ".join(f"{floors[k]['mean']:>14.4f}" for k in DISTRIBUTIONS)
        )

    resolved = resolve_locally(args.trials)
    if resolved:
        print("\nResolved exactly, where this repo holds the raw probabilities:")
        for r in resolved:
            print(
                f"  {r['id']:<24} n={r['n']:<5} ECE {r['ece']:.4f}  "
                f"floor {r['floor']:.4f}  {r['ratio']:.2f}x  {r['verdict']}"
            )
        print(
            "  The simulated range above spans noise to real for the same figure;\n"
            "  the raw pairs collapse it to one answer. That is the whole argument\n"
            "  for publishing them."
        )

    print(
        "\nA claim marked UNRESOLVABLE is not refuted. It means the study reported\n"
        "an ECE without the probability distribution needed to interpret it, so the\n"
        "same figure reads as noise or as real depending on an unstated fact.\n"
        "Publishing the raw (probability, outcome) pairs resolves it immediately."
    )

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)
            fh.write("\n")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
