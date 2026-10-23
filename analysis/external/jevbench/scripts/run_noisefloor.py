#!/usr/bin/env python3
"""Noise floor for Khosla jevbench EXP-1 soft top-label dECE (issue #17, step 3).

Local only. No Jev API calls. No writes outside this directory.

Question: what dECE does Khosla's METHOD produce when there is no real
miscalibration to find -- i.e. for predictors that are perfectly calibrated
under his own target definition (soft correctness = share of the 100
ChaosNLI annotators who chose the model's top label; confidence = the
model's probability for that label)?

Estimator (reused, not reimplemented, from the cloned repo
../jevbench, commit tree as cloned):
  - jevbench.metrics._ece_from_bins / expected_calibration_error:
      ECE = sum_b (n_b/N) * | mean(conf in b) - mean(correct in b) |,
      M=10 uniform bins on [0,1] (edges linspace(0,1,11); bin index via
      np.digitize(conf, edges[1:-1], right=False), clipped to [0,9];
      conf==1.0 -> bin 9), bin confidence = MEAN of conf in bin,
      empty bins contribute 0.
  - jevbench.power._soft_ece_uniform: the fast path used by his corrected
    primary; bin index min(9, int(conf*10)). Cross-checked against
    _ece_from_bins below (must agree to <1e-9).
  - Bias correction (Amendment 8, jevbench.power.soft_delta_ece_corrected /
    expected_ece_under_calibration, kappa=20, annotator_n=100):
      E0_stratum = mean ECE over calibrated Beta-Binomial draws at the
        stratum's own observed top probabilities:
        s_i ~ Beta(kappa*p_i, kappa*(1-p_i)); share = Binomial(100, s_i)/100;
        confidence held at p_i.
      corrected dECE = (ECE_h - E0_h) - (ECE_e - E0_e) = raw dECE - (E0_h-E0_e).
      His interval: percentile bootstrap of corrected dECE with E0 fixed.
      His p-value: two-sided vs simulated null distribution of raw dECE
        at the observed probabilities.
    Per Monte-Carlo replicate here we compute raw ECE per stratum and
    corrected dECE = raw - bias0, with bias0 from his
    expected_ece_under_calibration at that replicate's confidences.
    The replicate distribution itself is the null distribution, so no
    per-replicate bootstrap CI is needed.

Data (his packaged, hash-locked files):
  ../jevbench/datasets/chaosnli/items.jsonl  (sha256 matches PREREGISTRATION.md)
  ../jevbench/datasets/chaosnli/labels.jsonl  (sha256 matches PREREGISTRATION.md)
  Primary items only (role == "primary"): 750 easy (tier == "easy") +
  750 hard (tier == "hard"); 100 paraphrase items excluded, as in EXP-1.
  label_dist order: entailment, neutral, contradiction; counts sum to 100.

Predictor variants (top label = argmax of the item's annotator distribution
for every variant; ties broken by numpy argmax = first label; the picked
label's share is identical under any tie-break):
  det          conf_i = true (empirical) share of pick; target = same share.
               Itemwise conf == correctness, so this is the degenerate null
               his Amendment 7 warns about -- included as the anchor.
  fresh_target conf_i = true share; target per replicate = share of pick in
               a FRESH Multinomial(100, label_dist) draw. Mimics scoring a
               latent-calibrated predictor against finite (100) annotations.
  fresh_conf   conf_i per replicate = share of pick in a FRESH
               Multinomial(100, label_dist) draw; target = empirical share.
               (The sampling variant as literally specified in the work order.)
  const        conf_i = global (pooled 1500-item) mean top-label share for
               every item; target = empirical share of pick. Deterministic.
  gauss        conf_i = clip(true share + N(0, 0.1), 0.001, 0.999) per
               replicate; target = empirical share of pick.

Seed: MASTER_SEED below; per-variant generators spawned from one
SeedSequence so the whole run is reproducible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import scipy
import pandas as pd
import sklearn

HERE = Path(__file__).resolve().parent
REPO = HERE.parent / "jevbench"
sys.path.insert(0, str(REPO))

from jevbench.metrics import (  # noqa: E402
    _ece_from_bins,
    expected_calibration_error,
    soft_correctness,
)
from jevbench.power import (  # noqa: E402
    SOFT_NULL_OPERATING_KAPPA,
    _soft_ece_uniform,
    expected_ece_under_calibration,
    soft_delta_ece_corrected,
)

MASTER_SEED = 20261021
KAPPA = float(SOFT_NULL_OPERATING_KAPPA)  # 20.0, his operating value
ANNOTATOR_N = 100
N_BINS = 10
CLAIMED_CORRECTED = 0.2636222846666666   # results/exp1.json jev.corrected_soft
CLAIMED_RAW_POINT = 0.26306666666666667  # results/exp1.json primary_delta_ece.point
CLAIMED_ECE_EASY = 0.07598666666666667
CLAIMED_ECE_HARD = 0.3390533333333334
CLAIMED_CI_PCT = [0.24333333333333346, 0.27809366666666674]


def load_strata() -> dict:
    def load_jsonl(p: Path):
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

    items = load_jsonl(REPO / "datasets/chaosnli/items.jsonl")
    labels = {r["id"]: r for r in load_jsonl(REPO / "datasets/chaosnli/labels.jsonl")}
    hashes = {
        name: hashlib.sha256((REPO / f"datasets/chaosnli/{name}").read_bytes()).hexdigest()
        for name in ("items.jsonl", "labels.jsonl")
    }
    out = {"hashes": hashes}
    for tier in ("easy", "hard"):
        sel = [r for r in items if r["role"] == "primary" and r["tier"] == tier]
        assert len(sel) == 750, (tier, len(sel))
        dist = np.array([labels[r["id"]]["label_dist"] for r in sel], dtype=float)
        counts = np.array([labels[r["id"]]["label_count"] for r in sel], dtype=float)
        assert np.all(counts.sum(axis=1) == 100)
        assert np.allclose(dist, counts / 100.0)
        pick = dist.argmax(axis=1)
        out[tier] = {
            "ids": [r["id"] for r in sel],
            "dist": dist,
            "pick": pick,
            "share": dist[np.arange(len(sel)), pick],  # max share per item
        }
    return out


def ece_his(conf: np.ndarray, correct: np.ndarray) -> float:
    """His ECE via metrics._ece_from_bins (core of expected_calibration_error)."""
    return float(_ece_from_bins(np.asarray(conf, float), np.asarray(correct, float),
                                N_BINS, "uniform").ece)


def summarise(x: np.ndarray) -> dict:
    x = np.asarray(x, dtype=float)
    return {
        "n": int(x.size),
        "mean": float(x.mean()),
        "sd": float(x.std(ddof=1)) if x.size > 1 else 0.0,
        "min": float(x.min()),
        "p025": float(np.quantile(x, 0.025)),
        "p50": float(np.quantile(x, 0.5)),
        "p975": float(np.quantile(x, 0.975)),
        "max": float(x.max()),
    }


def e0_pair(conf_e: np.ndarray, conf_h: np.ndarray, rng, n_sims: int) -> tuple[float, float]:
    e0_e = expected_ece_under_calibration(conf_e, kappa=KAPPA, n_sims=n_sims, rng=rng,
                                           annotator_n=ANNOTATOR_N, n_bins=N_BINS)
    e0_h = expected_ece_under_calibration(conf_h, kappa=KAPPA, n_sims=n_sims, rng=rng,
                                           annotator_n=ANNOTATOR_N, n_bins=N_BINS)
    return float(e0_e), float(e0_h)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="smoke run, few reps, /tmp out")
    args = ap.parse_args()

    reps_main = 20 if args.quick else 1000      # fresh_target
    reps_var = 20 if args.quick else 400        # fresh_conf, gauss
    n_e0_var = 50 if args.quick else 250        # E0 sims per varying-conf replicate
    n_e0_fixed = 200 if args.quick else 2000    # his exp1 value

    t0 = time.time()
    strata = load_strata()
    easy, hard = strata["easy"], strata["hard"]
    s_e, s_h = easy["share"], hard["share"]
    global_mean_share = float(np.concatenate([s_e, s_h]).mean())

    results: dict = {
        "seed": MASTER_SEED,
        "kappa": KAPPA,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "pandas": pd.__version__,
            "sklearn": sklearn.__version__,
        },
        "data_hashes": strata["hashes"],
        "strata_summary": {
            t: {
                "n": int(len(strata[t]["share"])),
                "mean_top_share": float(strata[t]["share"].mean()),
                "min_top_share": float(strata[t]["share"].min()),
                "max_top_share": float(strata[t]["share"].max()),
                "mean_entropy_bits": float(
                    -(np.where(strata[t]["dist"] > 0,
                               strata[t]["dist"] * np.log2(np.where(strata[t]["dist"] > 0, strata[t]["dist"], 1)),
                               0)).sum(axis=1).mean()),
            } for t in ("easy", "hard")
        },
        "global_mean_top_share": global_mean_share,
        "claimed": {
            "ece_easy": CLAIMED_ECE_EASY, "ece_hard": CLAIMED_ECE_HARD,
            "delta_raw_point": CLAIMED_RAW_POINT,
            "delta_corrected": CLAIMED_CORRECTED,
            "ci_percentile": CLAIMED_CI_PCT,
        },
    }

    # ---- cross-check his two ECE implementations -------------------------
    rng_check = np.random.default_rng(MASTER_SEED + 1)
    maxdiff = 0.0
    for _ in range(200):
        c = rng_check.random(750)
        y = rng_check.random(750)
        maxdiff = max(maxdiff, abs(_soft_ece_uniform(c, y, N_BINS) - ece_his(c, y)))
    results["ece_impl_max_abs_diff_soft_vs_metrics"] = float(maxdiff)
    assert maxdiff < 1e-9

    # top-level API check on the deterministic null (probs = label_dist itself)
    for tier, st in (("easy", easy), ("hard", hard)):
        maj = st["dist"].argmax(axis=1)
        sc = soft_correctness(st["dist"], st["dist"])
        res = expected_calibration_error(st["dist"], maj, n_bins=10, strategy="uniform",
                                         correctness=sc)
        results.setdefault("det_top_level_api_ece", {})[tier] = float(res.ece)

    ss = np.random.SeedSequence(MASTER_SEED)
    rng_e0, rng_det_corr, rng_ft, rng_fc, rng_gs = [
        np.random.default_rng(s) for s in ss.spawn(5)]

    # ---- E0 (his bias-correction expectation) at the null confidences ----
    e0_e_det, e0_h_det = e0_pair(s_e, s_h, rng_e0, n_e0_fixed)
    results["e0_at_null_conf"] = {"easy": e0_e_det, "hard": e0_h_det,
                                  "bias0_delta": e0_h_det - e0_e_det,
                                  "n_sims": n_e0_fixed, "kappa": KAPPA}

    variants: dict = {}

    # ---- det -------------------------------------------------------------
    det = {
        "ece_easy": ece_his(s_e, s_e), "ece_hard": ece_his(s_h, s_h),
        "occupancy_easy": np.histogram(s_e, bins=np.linspace(0, 1, 11))[0].tolist(),
        "occupancy_hard": np.histogram(s_h, bins=np.linspace(0, 1, 11))[0].tolist(),
    }
    det["delta_raw"] = det["ece_hard"] - det["ece_easy"]
    det["delta_corrected"] = det["delta_raw"] - (e0_h_det - e0_e_det)
    # his full corrected pipeline (bootstrap CI + parametric p) on the null
    full = soft_delta_ece_corrected(
        s_h, s_h, s_e, s_e, kappa=KAPPA, n_boot=2000, n_e0=n_e0_fixed,
        n_null_pval=2000, rng=rng_det_corr, n_bins=N_BINS, annotator_n=ANNOTATOR_N)
    det["his_soft_delta_ece_corrected_full"] = {k: (float(v) if isinstance(v, float) else v)
                                                for k, v in full.items()}
    variants["det"] = det

    # ---- const ------------------------------------------------------------
    cst_conf_e = np.full_like(s_e, global_mean_share)
    cst_conf_h = np.full_like(s_h, global_mean_share)
    e0_e_c, e0_h_c = e0_pair(cst_conf_e, cst_conf_h, rng_e0, n_e0_fixed)
    cst = {"conf_value": global_mean_share,
           "ece_easy": ece_his(cst_conf_e, s_e), "ece_hard": ece_his(cst_conf_h, s_h),
           "e0_easy": e0_e_c, "e0_hard": e0_h_c}
    cst["delta_raw"] = cst["ece_hard"] - cst["ece_easy"]
    cst["delta_corrected"] = cst["delta_raw"] - (e0_h_c - e0_e_c)
    variants["const"] = cst

    # ---- fresh_target ------------------------------------------------------
    ft_e, ft_h, ft_d, ft_dc = [], [], [], []
    for _ in range(reps_main):
        te = rng_ft.multinomial(ANNOTATOR_N, easy["dist"])[np.arange(750), easy["pick"]] / 100.0
        th = rng_ft.multinomial(ANNOTATOR_N, hard["dist"])[np.arange(750), hard["pick"]] / 100.0
        ee, eh = ece_his(s_e, te), ece_his(s_h, th)
        ft_e.append(ee); ft_h.append(eh); ft_d.append(eh - ee)
        ft_dc.append((eh - ee) - (e0_h_det - e0_e_det))
    variants["fresh_target"] = {
        "reps": reps_main,
        "ece_easy": summarise(ft_e), "ece_hard": summarise(ft_h),
        "delta_raw": summarise(ft_d), "delta_corrected": summarise(ft_dc),
        "frac_delta_corrected_ge_claimed": float(np.mean(np.array(ft_dc) >= CLAIMED_CORRECTED)),
        "frac_delta_raw_ge_claimed_ci_low": float(np.mean(np.array(ft_d) >= CLAIMED_CI_PCT[0])),
    }

    # ---- fresh_conf ---------------------------------------------------------
    fc_e, fc_h, fc_d, fc_dc = [], [], [], []
    for _ in range(reps_var):
        ce = rng_fc.multinomial(ANNOTATOR_N, easy["dist"])[np.arange(750), easy["pick"]] / 100.0
        ch = rng_fc.multinomial(ANNOTATOR_N, hard["dist"])[np.arange(750), hard["pick"]] / 100.0
        ee, eh = ece_his(ce, s_e), ece_his(ch, s_h)
        e0e, e0h = e0_pair(ce, ch, rng_fc, n_e0_var)
        fc_e.append(ee); fc_h.append(eh); fc_d.append(eh - ee)
        fc_dc.append((eh - ee) - (e0h - e0e))
    variants["fresh_conf"] = {
        "reps": reps_var, "n_e0_per_rep": n_e0_var,
        "ece_easy": summarise(fc_e), "ece_hard": summarise(fc_h),
        "delta_raw": summarise(fc_d), "delta_corrected": summarise(fc_dc),
        "frac_delta_corrected_ge_claimed": float(np.mean(np.array(fc_dc) >= CLAIMED_CORRECTED)),
        "frac_delta_raw_ge_claimed_ci_low": float(np.mean(np.array(fc_d) >= CLAIMED_CI_PCT[0])),
    }

    # ---- gauss ----------------------------------------------------------------
    gs_e, gs_h, gs_d, gs_dc = [], [], [], []
    for _ in range(reps_var):
        ce = np.clip(s_e + rng_gs.normal(0.0, 0.1, size=750), 0.001, 0.999)
        ch = np.clip(s_h + rng_gs.normal(0.0, 0.1, size=750), 0.001, 0.999)
        ee, eh = ece_his(ce, s_e), ece_his(ch, s_h)
        e0e, e0h = e0_pair(ce, ch, rng_gs, n_e0_var)
        gs_e.append(ee); gs_h.append(eh); gs_d.append(eh - ee)
        gs_dc.append((eh - ee) - (e0h - e0e))
    variants["gauss"] = {
        "reps": reps_var, "n_e0_per_rep": n_e0_var, "sigma": 0.1,
        "ece_easy": summarise(gs_e), "ece_hard": summarise(gs_h),
        "delta_raw": summarise(gs_d), "delta_corrected": summarise(gs_dc),
        "frac_delta_corrected_ge_claimed": float(np.mean(np.array(gs_dc) >= CLAIMED_CORRECTED)),
        "frac_delta_raw_ge_claimed_ci_low": float(np.mean(np.array(gs_d) >= CLAIMED_CI_PCT[0])),
    }

    results["variants"] = variants
    results["runtime_s"] = time.time() - t0

    out = Path("/tmp/noisefloor_quick.json") if args.quick else HERE / "results.json"
    out.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
