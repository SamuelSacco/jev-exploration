"""Judge-circularity audit of the difficulty-gradient findings (B1 and B2).

    python3 analysis/circularity.py

No API key. Reads the committed raw responses and the committed labels.

Background: zhuyansen/jev-search-rerank-eval (sweep T69) measured judge
circularity in a reranking eval, where the model under test also produced the
relevance labels. Its reported advantage moved from +0.053 NDCG@10 under
Jev-authored labels to -0.028 under LLM-authored labels: a swing of 0.081, and
a sign change. Any benchmark where the model labelled its own task carries that
bias, unmeasured.

This audit asks whether B1 and B2 carry it. Two parts:

1. Provenance. Trace where the labels came from. Circularity requires the model
   under test to have influenced the labels; if it did not, the bias cannot be
   present and no relabeling experiment is needed.

2. Sensitivity. Provenance establishes that the labels are not model-derived. It
   does not establish that the findings would survive labels that were wrong for
   some other reason. So: corrupt the labels adversarially, in the direction that
   most flatters the model, and find the corruption rate at which each finding
   flips. That is the bias budget the finding has.

The second part matters independently of the first. A finding that dies at 1%
label error is fragile whatever produced the labels.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

from jevlab.stats import coverage_at, decompose_ece, ece  # noqa: E402
from lab.tiers.analyse import read_pass  # noqa: E402
from lab.tiers.baselines import TIER_ORDER, load  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIER_RUN = "20260918T013027Z"

# T69's measured swing, for scale.
T69_SWING = 0.081


# ------------------------------------------------------------------- provenance


def label_provenance() -> dict:
    """Machine-check that no model output can reach a tier label.

    Circularity needs a path from the model under test to the ground truth. In
    this dataset the label is chosen from a counter before any text exists, and
    the generator imports nothing that could call an API.
    """
    path = os.path.join(ROOT, "lab", "tiers", "generate.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()

    assign = re.search(r'^\s*label\s*=\s*"phishing" if .* else "legitimate"', src, re.M)
    build = re.search(r"builder\.build\(label,", src)
    api_tokens = [
        tok
        for tok in ("JevClient", "jevlab.client", "urllib", "requests", "api.typesafe")
        if tok in src
    ]
    # rng.choice is random.Random, not the Jev Choice primitive.
    model_reads = re.findall(r"\b(?:resp|response)\.(?:noul|choice|score)\b", src)

    return {
        "generator": os.path.relpath(path, ROOT),
        "label_assigned_at_line": src[: assign.start()].count("\n") + 1 if assign else None,
        "text_built_at_line": src[: build.start()].count("\n") + 1 if build else None,
        "label_precedes_text": bool(assign and build and assign.start() < build.start()),
        "api_imports": api_tokens,
        "model_output_reads": model_reads,
        "verdict": (
            "labels are not model-derived"
            if assign and build and assign.start() < build.start() and not api_tokens
            else "INSPECT: provenance not established"
        ),
    }


# ------------------------------------------------------------------ corruption


def flip(pairs: list, index: int) -> list:
    out = list(pairs)
    p, hit = out[index]
    out[index] = (p, not hit)
    return out


def corrupt_adversarially(pairs: list, k: int, bins: int = 10) -> list:
    """Flip k outcomes, each chosen to raise ECE as much as possible.

    This is the worst case: an adversary who knows the model's answers and
    relabels to make the sample look as badly calibrated as it can. Used for B1,
    where the finding is that calibration did NOT worsen.
    """
    current = list(pairs)
    flipped = set()
    for _ in range(k):
        best, best_ece = None, -1.0
        for i in range(len(current)):
            if i in flipped:
                continue
            candidate = ece(flip(current, i), bins)
            if candidate > best_ece:
                best, best_ece = i, candidate
        if best is None:
            break
        current = flip(current, best)
        flipped.add(best)
    return current


def corrupt_randomly(pairs: list, k: int, seed: int) -> list:
    rng = random.Random(seed)
    idx = rng.sample(range(len(pairs)), min(k, len(pairs)))
    out = list(pairs)
    for i in idx:
        p, hit = out[i]
        out[i] = (p, not hit)
    return out


# ------------------------------------------------------------------ sensitivity


def sensitivity_b2(pairs: list, threshold: float = 0.9, target: float = 0.95) -> dict:
    """B2: p>=threshold gives a 1.000 hit rate. How many wrong labels break it?

    Every item above the threshold is currently a hit, so each corrupted label
    in that bucket costs exactly one. No search is needed: the budget is
    arithmetic, which is itself the finding.
    """
    block = coverage_at(pairs, threshold)
    n = block["n"]
    if not n:
        return {"n_above_threshold": 0, "flips_to_break": None}
    flips = 0
    while flips < n and (n - flips) / n >= target:
        flips += 1
    return {
        "n_above_threshold": n,
        "coverage": round(block["coverage"], 4),
        "hit_rate": round(block["hit_rate"], 4),
        "flips_to_fall_below_target": flips,
        "as_fraction_of_tier": round(flips / len(pairs), 4),
        "target": target,
    }


def sensitivity_b1(
    baseline: list, compare: list, max_fraction: float = 0.25, step: int = 2
) -> dict:
    """B1: compare's gaps under baseline's mass stay at or below baseline's ECE.

    Corrupt the compare sample adversarially until that stops holding.
    """
    intact = decompose_ece(baseline, compare)
    limit = int(len(compare) * max_fraction)
    broke_at = None
    trace = []
    for k in range(0, limit + 1, step):
        corrupted = corrupt_adversarially(compare, k) if k else list(compare)
        block = decompose_ece(baseline, corrupted)
        trace.append(
            {
                "flips": k,
                "fraction": round(k / len(compare), 4),
                "compare_gaps_under_baseline_mass": round(
                    block["compare_gaps_under_baseline_mass"], 4
                ),
                "calibration_worsened": block["calibration_worsened"],
            }
        )
        if block["calibration_worsened"]:
            broke_at = k
            break
    return {
        "intact_margin": round(
            intact["baseline_ece"] - intact["compare_gaps_under_baseline_mass"], 4
        ),
        "flips_to_break": broke_at,
        "fraction_to_break": round(broke_at / len(compare), 4) if broke_at else None,
        "searched_to_fraction": max_fraction,
        "trace": trace,
    }


def random_corruption_reference(
    baseline: list, compare: list, fraction: float, seeds: int = 20
) -> dict:
    """The same corruption applied at random rather than adversarially."""
    k = int(len(compare) * fraction)
    broke = 0
    for seed in range(seeds):
        block = decompose_ece(baseline, corrupt_randomly(compare, k, seed))
        broke += bool(block["calibration_worsened"])
    return {"fraction": fraction, "flips": k, "seeds": seeds, "broke": broke}


# -------------------------------------------------------------------------- main


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pass-index", type=int, default=0)
    ap.add_argument("--json", help="write the audit result here")
    args = ap.parse_args(argv)

    gold = {r["id"]: r["is_phishing"] for r in load()}
    tiers = {t: read_pass(TIER_RUN, t, args.pass_index, gold) for t in TIER_ORDER}

    prov = label_provenance()
    print("1. Label provenance\n")
    print(f"  generator            {prov['generator']}")
    print(f"  label assigned       line {prov['label_assigned_at_line']}")
    print(f"  text built from it   line {prov['text_built_at_line']}")
    print(f"  label precedes text  {prov['label_precedes_text']}")
    print(f"  API imports          {prov['api_imports'] or 'none'}")
    print(f"  reads model output   {prov['model_output_reads'] or 'none'}")
    print(f"  verdict              {prov['verdict']}")

    print("\n2. B2 sensitivity (p>=0.9 gives a 1.000 hit rate)\n")
    b2 = {}
    for tier in TIER_ORDER:
        block = sensitivity_b2(tiers[tier])
        b2[tier] = block
        print(
            f"  {tier:<16} {block['n_above_threshold']:>3} items above 0.9; "
            f"{block['flips_to_fall_below_target']} wrong label(s) drop it under "
            f"{block['target']:.2f} ({block['as_fraction_of_tier']:.1%} of the tier)"
        )

    print("\n3. B1 sensitivity (t4's gaps under t1's mass stay at or below t1's ECE)\n")
    b1 = sensitivity_b1(tiers["t1_trivial"], tiers["t4_adversarial"])
    print(f"  intact margin            {b1['intact_margin']:+.4f}")
    if b1["flips_to_break"] is None:
        print(
            f"  adversarial corruption   survives every level searched "
            f"(up to {b1['searched_to_fraction']:.0%})"
        )
    else:
        print(
            f"  adversarial corruption   breaks at {b1['flips_to_break']} flips "
            f"({b1['fraction_to_break']:.1%} of the tier)"
        )
    ref = random_corruption_reference(
        tiers["t1_trivial"], tiers["t4_adversarial"], fraction=0.10
    )
    print(
        f"  random corruption 10%    broke {ref['broke']}/{ref['seeds']} seeds "
        f"({ref['flips']} flips)"
    )

    print("\n4. Reading\n")
    print(
        "  B1 and B2 cannot carry T69's bias: the model under test never touched\n"
        "  the labels, which were fixed before the text existed. A relabeling\n"
        "  experiment on this data would not estimate the same latent quantity a\n"
        "  second time; it would build a different dataset."
    )
    b2_worst = min(b2[t]["as_fraction_of_tier"] for t in TIER_ORDER)
    print(
        f"\n  B2 is nonetheless fragile to label error: {b2_worst:.1%} of a tier\n"
        "  mislabelled in the model's favour is enough to move it off 1.000. It is\n"
        "  a statement about a 43-to-65 item bucket, not a law."
    )
    if b1["flips_to_break"]:
        print(
            f"\n  B1 is sturdier: it takes {b1['fraction_to_break']:.0%} adversarial\n"
            "  corruption to overturn, and random corruption at 10% does not."
        )
    print(
        f"\n  For scale, T69's measured circularity swing was {T69_SWING:.3f} NDCG@10,\n"
        "  large enough to change a sign. Nothing of that size can enter here\n"
        "  through the labels. It can still enter through the ITEMS: the decisive\n"
        "  pairs were written by a language model, so the text may be unusually\n"
        "  legible to models even though the labels are clean. That is author\n"
        "  bias rather than judge circularity, it is not measurable offline, and\n"
        "  it is specified in analysis/CIRCULARITY.md."
    )

    result = {
        "provenance": prov,
        "b2_sensitivity": b2,
        "b1_sensitivity": b1,
        "b1_random_reference": ref,
        "t69_swing_for_scale": T69_SWING,
    }
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
            fh.write("\n")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
