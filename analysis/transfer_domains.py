"""Issue #9: evaluate whether the calibration correction transferred.

    python3 analysis/transfer_domains.py

No API key and no network. Reads the answers `lab/exp_transfer.py` wrote and the
labels committed in `lab/domains/dataset.jsonl`, then scores the three
preregistered hypotheses stated in that runner's docstring.

Scoring is separated from running so the verdict comes from committed data and
can be recomputed by anyone, and so the hypotheses cannot be adjusted after the
numbers arrive: they are read back out of the results file, which the runner
wrote before it made a call.

H2 (the intercept/slope decomposition) is scored with uncertainty, not just
point estimates. The two code_security slices share their items -- only the
base rate differs -- so one bootstrap resample draws item indices with
replacement and refits Platt on both slices from the same draw; the percentile
intervals on |slope_rare - slope_base| and |intercept_rare - intercept_base|
are the 95% bootstrap CIs. The verdict rule, stated exactly:

  PROVEN   point estimates clear the preregistered thresholds (intercept moves
           > 0.8 logits, slope moves < 0.5) AND the CIs clear them too: the
           intercept CI's *lower* bound exceeds 0.8 and the slope CI's *upper*
           bound sits below 0.5.
  PARTIAL  point estimates clear the thresholds but at least one CI does not
           fully clear them (the honest downgrade when uncertainty is wide).
  REFUTED  the slope moves more than the intercept does (the preregistered
           falsifier), judged on point estimates.
  PARTIAL  otherwise (point estimates do not clear the thresholds and the
           falsifier does not fire).

The RNG, percentile method, and seed convention match jevlab.stats.bootstrap_ci;
it is written as one loop rather than two bootstrap_ci calls so both
differences come from the same resamples.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

from jevlab.calibration import (  # noqa: E402
    apply_map,
    fit_platt_checked,
    fit_platt_intercept,
)
from jevlab.run_meta import emit, print_header  # noqa: E402
from jevlab.stats import ece_with_floor, wilson  # noqa: E402
from lab.domains.baselines import (  # noqa: E402
    DATASET_NAME,
    SLICE_ORDER,
    dataset_version,
    lexical,
    load,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ANSWERS = os.path.join(ROOT, "lab", "domains", "transfer_answers.json")

EMAIL_SLOPE_BAND = (2.11, 2.61)
FALSIFYING_BAND = (1.60, 3.10)
# Midpoint of the e-mail band: the single number the recipe says to reuse.
EMAIL_SLOPE = 2.34
REFIT_LABELS = 50

# H2 decomposition thresholds, from the preregistration in lab/exp_transfer.py:
# between code_security and code_security_rare the intercept must move by more
# than H2_INTERCEPT_MOVED logits while the slope moves by less than
# H2_SLOPE_STABLE. H2 is PROVEN only if the 95% bootstrap CIs clear the same
# thresholds (see the module docstring for the exact rule).
H2_INTERCEPT_MOVED = 0.8
H2_SLOPE_STABLE = 0.5
H2_BOOTSTRAP_RESAMPLES = 2_000
H2_BOOTSTRAP_SEED = 0
H2_BOOTSTRAP_ALPHA = 0.05


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


def h2_pairs(doc: dict, rows: list) -> tuple | None:
    """The two code_security slices' (p, gold) pairs, aligned item by item.

    The slices share their items (same qids, same questions); only the base
    rate differs, so the bootstrap draws one index resample for both slices.
    Returns None when either slice is missing or too small to fit.
    """
    blocks = doc.get("slices", {})
    if "code_security" not in blocks or "code_security_rare" not in blocks:
        return None
    gold = {
        (r["slice"], r["id"]): r["is_positive"]
        for r in rows
        if r["slice"] in ("code_security", "code_security_rare")
    }
    probs_base = blocks["code_security"]["probabilities"]
    probs_rare = blocks["code_security_rare"]["probabilities"]
    qids = sorted(set(probs_base) & set(probs_rare))
    base = [
        (probs_base[q], gold[("code_security", q)])
        for q in qids
        if ("code_security", q) in gold
    ]
    rare = [
        (probs_rare[q], gold[("code_security_rare", q)])
        for q in qids
        if ("code_security_rare", q) in gold
    ]
    if len(base) != len(rare) or len(base) < 20:
        return None
    return base, rare


def h2_bootstrap(
    base_pairs: list,
    rare_pairs: list,
    resamples: int = H2_BOOTSTRAP_RESAMPLES,
    seed: int = H2_BOOTSTRAP_SEED,
    alpha: float = H2_BOOTSTRAP_ALPHA,
) -> dict:
    """Paired percentile bootstrap for the H2 slope/intercept differences.

    One resample draws item indices with replacement and refits Platt on both
    slices from the same draw (the slices share their items). Each resample's
    |slope_rare - slope_base| and |intercept_rare - intercept_base| form the
    two bootstrap distributions; the reported intervals are their percentiles,
    computed exactly the way jevlab.stats.bootstrap_ci does it, with the same
    seeded RNG. Resamples whose fit is not identified are skipped rather than
    reported -- a runaway Newton slope is a numerical artefact, not a draw
    from the sampling distribution -- and the skip count is reported so a
    reader can see whether the interval rests on shaky fits.
    """
    n = len(base_pairs)
    rng = random.Random(seed)
    d_slopes, d_ints = [], []
    skipped = 0
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        map_base, diag_base = fit_platt_checked([base_pairs[i] for i in idx])
        map_rare, diag_rare = fit_platt_checked([rare_pairs[i] for i in idx])
        if not (diag_base["identified"] and diag_rare["identified"]):
            skipped += 1
            continue
        d_slopes.append(abs(map_rare.a - map_base.a))
        d_ints.append(abs(map_rare.b - map_base.b))

    def percentile(values: list) -> tuple | None:
        if not values:
            return None
        values.sort()
        m = len(values)
        return (
            values[int((alpha / 2) * m)],
            values[min(m - 1, int((1 - alpha / 2) * m))],
        )

    used = len(d_slopes)
    stable = used >= max(100, resamples // 2)
    return {
        "resamples": resamples,
        "resamples_used": used,
        "resamples_skipped": skipped,
        "seed": seed,
        "alpha": alpha,
        "stable": stable,
        "slope_ci": percentile(d_slopes) if stable else None,
        "intercept_ci": percentile(d_ints) if stable else None,
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


def verdicts(fits: dict, recipes: dict, h2: dict | None = None) -> dict:
    """Score the three preregistered hypotheses. PROVEN / REFUTED / UNVERIFIABLE.

    `h2` is the output of `h2_bootstrap` for the two code_security slices, or
    None when it was not computed. H2 is PROVEN only when the point estimates
    clear the preregistered thresholds (intercept moves > 0.8 logits, slope
    moves < 0.5) *and* the 95% bootstrap CIs clear them too -- the intercept
    CI's lower bound above 0.8, the slope CI's upper bound below 0.5. Point
    estimates that clear the thresholds without the CIs earn PARTIAL, never
    PROVEN: a decomposition declared from point estimates alone has no measured
    uncertainty behind it.
    """
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
        point_clears = d_int > H2_INTERCEPT_MOVED and d_slope < H2_SLOPE_STABLE
        block = {
            "slope_moved": round(d_slope, 4),
            "intercept_moved": round(d_int, 4),
        }
        if h2 and h2.get("stable") and h2.get("slope_ci") and h2.get("intercept_ci"):
            s_lo, s_hi = h2["slope_ci"]
            i_lo, i_hi = h2["intercept_ci"]
            block["slope_moved_ci95"] = [round(s_lo, 4), round(s_hi, 4)]
            block["intercept_moved_ci95"] = [round(i_lo, 4), round(i_hi, 4)]
            block["bootstrap_resamples_used"] = h2["resamples_used"]
            block["bootstrap_resamples_skipped"] = h2["resamples_skipped"]
            ci_clears = i_lo > H2_INTERCEPT_MOVED and s_hi < H2_SLOPE_STABLE
            if point_clears and ci_clears:
                verdict, why = "PROVEN", None
            elif point_clears:
                verdict = "PARTIAL"
                why = (
                    "point estimates clear the thresholds "
                    f"(intercept moved {d_int:.2f} > {H2_INTERCEPT_MOVED}, "
                    f"slope moved {d_slope:.2f} < {H2_SLOPE_STABLE}) but the 95% "
                    "bootstrap CIs do not fully clear them: "
                    f"intercept CI [{i_lo:.2f}, {i_hi:.2f}], "
                    f"slope CI [{s_lo:.2f}, {s_hi:.2f}]"
                )
            elif d_slope > d_int:
                verdict, why = "REFUTED", None
            else:
                verdict, why = "PARTIAL", None
        else:
            # No usable bootstrap CIs (unit-test seam only; analyse always
            # computes them). Point estimates alone cannot PROVE the
            # decomposition, so PROVEN is unreachable on this path.
            if point_clears:
                verdict = "PARTIAL"
                why = "no bootstrap CIs: point estimates alone cannot PROVE H2"
            elif d_slope > d_int:
                verdict, why = "REFUTED", None
            else:
                verdict, why = "PARTIAL", None
        block["verdict"] = verdict
        if why:
            block["why"] = why
        out["H2_decomposition_is_real"] = block
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
    paired = h2_pairs(doc, rows)
    h2 = h2_bootstrap(*paired) if paired else None
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
        "verdicts": verdicts(fits, recipes, h2=h2),
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
    meta = emit(
        task="analysis.transfer_domains",
        args=vars(args),
        datasets={DATASET_NAME: dataset_version()},
        # The transfer answers file records transport, not the model that
        # served the responses: model_id stays "unknown" rather than guessed.
        model_id=doc.get("model") or "unknown",
        transport=doc.get("transport") or "unknown",
    )
    print_header(meta)
    result = analyse(doc, load())
    result["run_meta"] = meta
    report(result)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
