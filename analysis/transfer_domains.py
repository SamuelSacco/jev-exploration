"""Issue #9: evaluate whether the calibration correction transferred.

    python3 analysis/transfer_domains.py

No API key and no network. Reads the answers `lab/exp_transfer.py` wrote and the
labels committed in `lab/domains/dataset.jsonl`, then scores the three
preregistered hypotheses stated in that runner's docstring.

Scoring is separated from running so the verdict comes from committed data and
can be recomputed by anyone, and so the hypotheses cannot be adjusted after the
numbers arrive: they are read back out of the results file, which the runner
wrote before it made a call.
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
    apply_map,
    fit_platt_checked,
    fit_platt_intercept,
)
from jevlab.stats import ece_with_floor, wilson  # noqa: E402
from lab.domains.baselines import SLICE_ORDER, lexical, load  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ANSWERS = os.path.join(ROOT, "lab", "domains", "transfer_answers.json")

EMAIL_SLOPE_BAND = (2.11, 2.61)
FALSIFYING_BAND = (1.60, 3.10)
# Midpoint of the e-mail band: the single number the recipe says to reuse.
EMAIL_SLOPE = 2.34
REFIT_LABELS = 50


def pairs_for(slice_name: str, probabilities: dict, rows: list) -> list:
    gold = {r["id"]: r["is_positive"] for r in rows if r["slice"] == slice_name}
    return [(p, gold[qid]) for qid, p in sorted(probabilities.items()) if qid in gold]


def fit_slice(pairs: list) -> dict:
    """Fit Platt on one slice, and say whether the fit is worth reading.

    A slice whose probabilities do not discriminate has no interior maximum
    likelihood, so Newton's method walks off and returns a slope in the
    thousands. Reporting that as "the slope did not transfer" would be a finding
    manufactured from a numerical failure, so `identified` gates every use.
    """
    mapping, diagnostics = fit_platt_checked(pairs)
    return {
        "slope": round(mapping.a, 4),
        "intercept": round(mapping.b, 4),
        **diagnostics,
    }


def accuracy(pairs: list, threshold: float = 0.5) -> dict:
    hits = sum(1 for p, gold in pairs if (p >= threshold) == gold)
    lo, hi = wilson(hits, len(pairs))
    return {
        "n": len(pairs),
        "accuracy": round(hits / len(pairs), 4),
        "ci95": [round(lo, 4), round(hi, 4)],
    }


def recipe(pairs: list, slope: float = EMAIL_SLOPE, labels: int = REFIT_LABELS) -> dict:
    """E-mail slope, intercept refit on the first `labels` items of the slice.

    The refit set is a prefix rather than a random sample: a deployment spends
    its label budget on what arrives first, not on a stratified draw.
    """
    before = ece_with_floor(pairs, trials=300)
    mapping = fit_platt_intercept(pairs[:labels], slope)
    after = ece_with_floor(apply_map(pairs, mapping), trials=300)
    return {
        "refit_labels": min(labels, len(pairs)),
        "refit_positives": sum(1 for _, gold in pairs[:labels] if gold),
        "intercept_refit": round(mapping.b, 4),
        "ece_before": round(before["ece"], 4),
        "ece_after": round(after["ece"], 4),
        "floor": round(before["floor_mean"], 4),
        "ratio_before": round(before["ratio"], 4),
        "ratio_after": round(after["ratio"], 4),
        "reduction": round(
            (before["ece"] - after["ece"]) / before["ece"], 4
        ) if before["ece"] else 0.0,
    }


def verdicts(fits: dict, recipes: dict) -> dict:
    """Score the three preregistered hypotheses. PROVEN / REFUTED / UNVERIFIABLE."""
    out = {}

    balanced = {s: f for s, f in fits.items() if not s.endswith("_rare")}
    unidentified = sorted(s for s, f in balanced.items() if not f.get("identified", True))
    slopes = {s: f["slope"] for s, f in balanced.items() if f.get("identified", True)}
    if not balanced:
        out["H1_slope_transfers"] = {"verdict": "UNVERIFIABLE", "why": "no slices fitted"}
    elif unidentified:
        out["H1_slope_transfers"] = {
            "verdict": "UNVERIFIABLE",
            "why": (
                "the Platt fit is not identified on "
                + ", ".join(unidentified)
                + ": those slices' probabilities do not discriminate, so the "
                "fitted slope is a numerical artefact, not a measurement"
            ),
            "unidentified": unidentified,
            "auc": {s: balanced[s].get("auc") for s in unidentified},
            "identified_slopes": slopes,
        }
    else:
        inside = {s: EMAIL_SLOPE_BAND[0] <= v <= EMAIL_SLOPE_BAND[1] for s, v in slopes.items()}
        falsified = [s for s, v in slopes.items()
                     if not FALSIFYING_BAND[0] <= v <= FALSIFYING_BAND[1]]
        out["H1_slope_transfers"] = {
            "verdict": "REFUTED" if falsified else ("PROVEN" if all(inside.values()) else "PARTIAL"),
            "slopes": slopes,
            "inside_email_band": inside,
            "outside_falsifying_band": falsified,
        }

    have_pair = "code_security" in fits and "code_security_rare" in fits
    pair_identified = have_pair and all(
        fits[s].get("identified", True) for s in ("code_security", "code_security_rare")
    )
    if have_pair and not pair_identified:
        out["H2_decomposition_is_real"] = {
            "verdict": "UNVERIFIABLE",
            "why": "the Platt fit is not identified on one of the two slices",
        }
    elif have_pair:
        base, rare = fits["code_security"], fits["code_security_rare"]
        d_slope = abs(rare["slope"] - base["slope"])
        d_int = abs(rare["intercept"] - base["intercept"])
        out["H2_decomposition_is_real"] = {
            "verdict": (
                "PROVEN" if (d_int > 0.8 and d_slope < 0.5)
                else ("REFUTED" if d_slope > d_int else "PARTIAL")
            ),
            "slope_moved": round(d_slope, 4),
            "intercept_moved": round(d_int, 4),
        }
    else:
        out["H2_decomposition_is_real"] = {
            "verdict": "UNVERIFIABLE",
            "why": "needs both code_security and code_security_rare",
        }

    if recipes:
        increased = [s for s, r in recipes.items() if r["ece_after"] > r["ece_before"]]
        met = {s: r["reduction"] >= 0.50 for s, r in recipes.items()}
        out["H3_recipe_works_out_of_domain"] = {
            "verdict": (
                "REFUTED" if increased
                else ("PROVEN" if all(met.values()) else "PARTIAL")
            ),
            "reductions": {s: r["reduction"] for s, r in recipes.items()},
            "increased_in": increased,
        }
    else:
        out["H3_recipe_works_out_of_domain"] = {"verdict": "UNVERIFIABLE", "why": "no slices"}
    return out


def analyse(doc: dict, rows: list) -> dict:
    fits, recipes, accs, eces, bars = {}, {}, {}, {}, {}
    by_slice = {s: [r for r in rows if r["slice"] == s] for s in SLICE_ORDER}
    for name, block in doc.get("slices", {}).items():
        pairs = pairs_for(name, block["probabilities"], rows)
        if len(pairs) < 20:
            continue
        fits[name] = fit_slice(pairs)
        recipes[name] = recipe(pairs)
        accs[name] = accuracy(pairs)
        eces[name] = round(ece_with_floor(pairs, trials=300)["ece"], 4)
        bars[name] = round(lexical(by_slice[name])["accuracy"], 4)
    return {
        "started_at": doc.get("started_at"),
        "transport": doc.get("transport"),
        "preregistered": doc.get("preregistered"),
        "fits": fits,
        "recipe": recipes,
        "accuracy": accs,
        "ece": eces,
        "lexical_bar": bars,
        "beats_lexical_bar": {
            s: accs[s]["ci95"][0] > bars[s] for s in accs
        },
        "verdicts": verdicts(fits, recipes),
    }


def report(result: dict) -> None:
    print("Cross-domain calibration transfer (issue #9)\n")
    print(f"  run        {result['started_at']}")
    print(f"  transport  {result['transport']}\n")

    header = (
        f"  {'slice':<22} {'n':>4} {'acc':>7} {'bar':>7} {'beats?':>7} "
        f"{'AUC':>6} {'slope':>9} {'intercept':>10} {'ECE':>7} {'after':>7}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name in SLICE_ORDER:
        if name not in result["fits"]:
            continue
        f, r, a = result["fits"][name], result["recipe"][name], result["accuracy"][name]
        slope = f"{f['slope']:.2f}" if f.get("identified", True) else "unident."
        intercept = f"{f['intercept']:.2f}" if f.get("identified", True) else "-"
        print(
            f"  {name:<22} {a['n']:>4} {a['accuracy']:>6.1%} "
            f"{result['lexical_bar'][name]:>6.1%} "
            f"{('yes' if result['beats_lexical_bar'][name] else 'NO'):>7} "
            f"{f.get('auc', 0.5):>6.3f} {slope:>9} {intercept:>10} "
            f"{r['ece_before']:>7.4f} {r['ece_after']:>7.4f}"
        )

    print("\n  Verdicts against what was written before the run:\n")
    for key, block in result["verdicts"].items():
        print(f"    {key}: {block['verdict']}")
        for k, v in block.items():
            if k != "verdict":
                print(f"      {k}: {v}")

    weak = [s for s, ok in result["beats_lexical_bar"].items() if not ok]
    if weak:
        print(
            f"\n  Caveat: on {', '.join(weak)} Jev's interval does not clear the\n"
            "  bag-of-words bar, so accuracy there measures vocabulary. The\n"
            "  calibration figures still stand, since they are about the shape of\n"
            "  the probabilities rather than about being right."
        )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--answers", default=DEFAULT_ANSWERS)
    ap.add_argument("--json", help="write the analysis here")
    args = ap.parse_args(argv)

    if not os.path.exists(args.answers):
        print(
            f"No answers at {args.answers}.\n"
            "Run the experiment first:\n"
            "  python3 lab/domains/baselines.py       # the dataset gate\n"
            "  python3 lab/exp_transfer.py --dry-run  # size it\n"
            "  JEV_TRANSPORT=... python3 lab/exp_transfer.py --repeat 3",
            file=sys.stderr,
        )
        return 1

    with open(args.answers, encoding="utf-8") as fh:
        doc = json.load(fh)
    result = analyse(doc, load())
    report(result)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
