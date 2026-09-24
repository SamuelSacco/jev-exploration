"""Score the endpoint and position probes.

    python3 analysis/response_shape.py --answers lab/response_shape_answers.json

No API key and no network. Reads what `lab/exp_response_shape.py` wrote and
scores the five hypotheses that runner recorded before its first call.

The position probe's arithmetic is the part worth reading. A reported "24.7% of
answers flip when you reorder the options" is only a position effect if the
same request, unchanged, flips less often than that. Jev is stochastic, so some
flips happen anyway. The probe runs the forward condition twice, and the
position effect is the reversed-versus-forward flip rate minus the
forward-versus-forward one, with a bootstrap interval on the paired difference.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jevlab.stats import bootstrap_ci, wilson  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(ROOT, "lab", "response_shape_answers.json")
BANDS = ["decisive", "moderate", "ambiguous"]


# ------------------------------------------------------------------- endpoints


def endpoint_stats(passes: list, items: dict) -> dict:
    """Exact-0 and exact-1 rates over Choice option probabilities, by band."""
    by_band = {band: {"zeros": 0, "ones": 0, "total": 0} for band in BANDS}
    zeros_on_gold = []
    for answers in passes:
        for qid, answer in answers.items():
            if "probabilities" not in answer or qid not in items:
                continue
            band = items[qid]["strength"]
            gold = items[qid]["gold"]
            for label, value in answer["probabilities"].items():
                by_band[band]["total"] += 1
                if value == 0.0:
                    by_band[band]["zeros"] += 1
                    if label == gold:
                        zeros_on_gold.append({"item": qid, "band": band})
                elif value == 1.0:
                    by_band[band]["ones"] += 1
    out = {}
    for band, counts in by_band.items():
        total = counts["total"] or 1
        out[band] = {
            "n_option_probabilities": counts["total"],
            "exact_0": counts["zeros"],
            "exact_0_rate": round(counts["zeros"] / total, 4),
            "exact_1": counts["ones"],
            "exact_1_rate": round(counts["ones"] / total, 4),
        }
    return {"by_band": out, "zeros_on_correct_option": zeros_on_gold}


def noul_endpoints(passes: list) -> dict:
    values = [
        answer["noul"]
        for answers in passes
        for answer in answers.values()
        if "noul" in answer
    ]
    if not values:
        return {"n": 0, "exact_0": 0, "exact_1": 0}
    return {
        "n": len(values),
        "exact_0": sum(1 for v in values if v == 0.0),
        "exact_1": sum(1 for v in values if v == 1.0),
        "min": min(values),
        "max": max(values),
    }


# -------------------------------------------------------------------- position


def flips(a_passes: list, b_passes: list, items: dict) -> list:
    """Per item: did the winner differ between the two conditions?

    Compared pass by pass, so a flip is one pair of requests disagreeing, not a
    majority vote hiding disagreement inside each condition.
    """
    out = []
    for a, b in zip(a_passes, b_passes):
        for qid in sorted(set(a) & set(b) & set(items)):
            if "choice" in a[qid] and "choice" in b[qid]:
                out.append(1.0 if a[qid]["choice"] != b[qid]["choice"] else 0.0)
    return out


def rate(values: list) -> dict:
    if not values:
        return {"n": 0, "rate": None}
    hits = int(sum(values))
    lo, hi = wilson(hits, len(values))
    return {
        "n": len(values),
        "flips": hits,
        "rate": round(hits / len(values), 4),
        "ci95": [round(lo, 4), round(hi, 4)],
    }


def position_effect(block: dict, items: dict) -> dict:
    reversed_flips = flips(block["forward"], block["reversed"], items)
    repeat_flips = flips(block["forward"], block["repeat"], items)
    n = min(len(reversed_flips), len(repeat_flips))
    deltas = [reversed_flips[i] - repeat_flips[i] for i in range(n)]
    lo, hi = bootstrap_ci(deltas, statistic=lambda xs: sum(xs) / len(xs)) if n else (0.0, 0.0)
    return {
        "reordered": rate(reversed_flips),
        "same_order_repeat": rate(repeat_flips),
        "effect": round(statistics.mean(deltas), 4) if deltas else None,
        "effect_ci95": [round(lo, 4), round(hi, 4)],
    }


# -------------------------------------------------------------------- verdicts


def verdicts(result: dict, reported_rate: float) -> dict:
    out = {}
    ends = result.get("endpoints")
    if not ends:
        for key in ("E1_endpoints_are_per_primitive", "E2_endpoints_retreat_with_evidence",
                    "E3_no_endpoint_on_a_correct_option"):
            out[key] = {"verdict": "UNVERIFIABLE", "why": "endpoint probe not run"}
    else:
        noul = ends["noul"]
        choice_zeros = sum(b["exact_0"] for b in ends["choice"]["by_band"].values())
        out["E1_endpoints_are_per_primitive"] = {
            "verdict": (
                "REFUTED" if (noul["exact_0"] or noul["exact_1"])
                else ("PROVEN" if choice_zeros else "UNVERIFIABLE")
            ),
            "choice_exact_0": choice_zeros,
            "noul_exact_0": noul["exact_0"],
            "noul_exact_1": noul["exact_1"],
            "noul_range": [noul.get("min"), noul.get("max")],
        }
        bands = ends["choice"]["by_band"]
        empty = [b for b in BANDS if not bands[b]["n_option_probabilities"]]
        if empty:
            # A band with no answers scores 0.0, which compares as "fewer
            # endpoints" and would report PROVEN from missing data.
            out["E2_endpoints_retreat_with_evidence"] = {
                "verdict": "UNVERIFIABLE",
                "why": f"no Choice answers in band(s): {', '.join(empty)}",
                "exact_0_rate_by_band": {b: bands[b]["exact_0_rate"] for b in BANDS},
            }
        else:
            decisive = bands["decisive"]["exact_0_rate"]
            ambiguous = bands["ambiguous"]["exact_0_rate"]
            out["E2_endpoints_retreat_with_evidence"] = {
                "verdict": "PROVEN" if ambiguous < decisive else "REFUTED",
                "exact_0_rate_by_band": {b: bands[b]["exact_0_rate"] for b in BANDS},
            }
        on_gold = ends["choice"]["zeros_on_correct_option"]
        out["E3_no_endpoint_on_a_correct_option"] = {
            "verdict": "REFUTED" if on_gold else "PROVEN",
            "instances": len(on_gold),
            "examples": on_gold[:5],
        }

    pos = result.get("position")
    if not pos or pos["effect"] is None:
        for key in ("P1_reordering_flips_more_than_repetition",
                    "P2_any_position_effect_is_below_the_reported_rate"):
            out[key] = {"verdict": "UNVERIFIABLE", "why": "position probe not run"}
    else:
        lo, hi = pos["effect_ci95"]
        out["P1_reordering_flips_more_than_repetition"] = {
            "verdict": "PROVEN" if lo > 0 else ("REFUTED" if lo <= 0 <= hi else "PARTIAL"),
            "reordered_rate": pos["reordered"]["rate"],
            "same_order_repeat_rate": pos["same_order_repeat"]["rate"],
            "effect": pos["effect"],
            "effect_ci95": pos["effect_ci95"],
        }
        out["P2_any_position_effect_is_below_the_reported_rate"] = {
            "verdict": "REFUTED" if lo > reported_rate else "PROVEN",
            "reported_rate": reported_rate,
            "effect_ci95": pos["effect_ci95"],
        }
    return out


def analyse(doc: dict) -> dict:
    items = doc.get("items", {})
    probes = doc.get("probes", {})
    result = {
        "started_at": doc.get("started_at"),
        "transport": doc.get("transport"),
        "preregistered": doc.get("preregistered"),
    }
    if "endpoints" in probes:
        result["endpoints"] = {
            "choice": endpoint_stats(probes["endpoints"]["choice"], items),
            "noul": noul_endpoints(probes["endpoints"]["noul"]),
        }
    if "position" in probes:
        result["position"] = position_effect(probes["position"], items)
    result["verdicts"] = verdicts(
        result, doc.get("reported_reversal_rate", 0.247)
    )
    return result


def report(result: dict) -> None:
    print("Response-shape probes\n")
    print(f"  run        {result['started_at']}")
    print(f"  transport  {result['transport']}\n")

    if "endpoints" in result:
        print("1. Endpoints, by evidence strength\n")
        bands = result["endpoints"]["choice"]["by_band"]
        print(f"  {'band':<12} {'options':>9} {'exact 0':>14} {'exact 1':>14}")
        for band in BANDS:
            b = bands[band]
            print(
                f"  {band:<12} {b['n_option_probabilities']:>9} "
                f"{b['exact_0']:>6} {b['exact_0_rate']:>7.1%} "
                f"{b['exact_1']:>6} {b['exact_1_rate']:>7.1%}"
            )
        noul = result["endpoints"]["noul"]
        print(
            f"\n  Noul on the same items: {noul['n']} answers, "
            f"{noul['exact_0']} at 0.00, {noul['exact_1']} at 1.00, "
            f"range [{noul.get('min')}, {noul.get('max')}]"
        )
        on_gold = result["endpoints"]["choice"]["zeros_on_correct_option"]
        print(f"  Exact 0 landing on the correct option: {len(on_gold)}")

    if "position" in result:
        pos = result["position"]
        print("\n2. Position\n")
        print(f"  reordered vs forward     {pos['reordered']['rate']:.1%} "
              f"({pos['reordered']['flips']}/{pos['reordered']['n']})")
        print(f"  forward vs forward       {pos['same_order_repeat']['rate']:.1%} "
              f"({pos['same_order_repeat']['flips']}/{pos['same_order_repeat']['n']})")
        print(f"  position effect          {pos['effect']:+.1%} "
              f"[{pos['effect_ci95'][0]:+.1%}, {pos['effect_ci95'][1]:+.1%}]")

    print("\nVerdicts, against what was written before the run:\n")
    for key, block in result["verdicts"].items():
        print(f"  {key}: {block['verdict']}")
        for k, v in block.items():
            if k != "verdict":
                print(f"    {k}: {v}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--answers", default=DEFAULT)
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    if not os.path.exists(args.answers):
        print(
            f"No answers at {args.answers}.\n"
            "Run it first:\n"
            "  python3 lab/response_shape_items.py --check\n"
            "  python3 lab/exp_response_shape.py --dry-run\n"
            "  JEV_TRANSPORT=... python3 lab/exp_response_shape.py --repeat 3",
            file=sys.stderr,
        )
        return 1

    with open(args.answers, encoding="utf-8") as fh:
        doc = json.load(fh)
    result = analyse(doc)
    report(result)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
