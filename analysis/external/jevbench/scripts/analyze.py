#!/usr/bin/env python3
"""Analysis of replication passes using HIS estimator code (jevbench.metrics/power).

Primary (pass A, mirroring his pass-0 convention and his seeds):
  - metrics-binning raw ECEs + delta_ece (seed 20260922, n_boot=10000, BCa+percentile)
  - power-binning soft_delta_ece_corrected (rng seed 20260922+91, kappa=20,
    n_boot=n_e0=n_null=2000) -> corrected dECE, CI, p
Robustness on pass A:
  - 15 uniform bins (power path, kappa=20)
  - 10 equal-mass (quantile) bins: raw dECE + stratified bootstrap percentile CI
    (E0 correction is defined by his code for uniform bins only; reported raw,
    with the uniform-bin bias0 noted — correction is ~0.002)
  - correction variants: kappa=10, kappa=50, and no correction (raw)
Per-pass (A/B/C): power-path ECEs, raw d, corrected d, CI; metrics-binning ECEs.
Cross-check: mean conf vs mean annotator agreement (soft target) per stratum.
Writes replication/results/analysis.json.
"""
import json, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve()
REP = HERE.parents[1]
JB = HERE.parents[2] / "jevbench"
sys.path.insert(0, str(JB))
from jevbench import metrics as M
from jevbench import power as P

LABELS = ["entailment", "neutral", "contradiction"]
SEED = 20260922

items = [json.loads(l) for l in (REP / "data/items_full.jsonl").read_text().splitlines() if l.strip()]
by_id = {r["id"]: r for r in items}

def load_pass(name):
    d = REP / "raw" / f"pass{name}"
    recs = {}
    for p in d.glob("*.json"):
        r = json.loads(p.read_text())
        if r.get("probabilities") is not None:
            recs[r["item_id"]] = r
    return recs

def arrays(recs, tier):
    ids = [r["id"] for r in items if r["tier"] == tier]
    missing = [i for i in ids if i not in recs]
    if missing:
        raise SystemExit(f"missing {len(missing)} items e.g. {missing[:3]}")
    probs = np.array([[recs[i]["probabilities"][lab] for lab in LABELS] for i in ids])
    dist = np.array([by_id[i]["label_dist"] for i in ids], dtype=float)
    maj = np.array([LABELS.index(by_id[i]["majority_label"]) for i in ids])
    return ids, probs, dist, maj

def corrected_block(probs_h, soft_h, probs_e, soft_e, kappa=20.0, n_bins=10, seed=SEED + 91):
    rng = np.random.default_rng(seed)
    return P.soft_delta_ece_corrected(
        probs_h.max(axis=1), soft_h, probs_e.max(axis=1), soft_e,
        kappa=kappa, n_boot=2000, n_e0=2000, n_null_pval=2000, rng=rng, n_bins=n_bins)

def ece_quantile(conf, soft, n_bins=10):
    qs = np.quantile(conf, np.linspace(0, 1, n_bins + 1))
    qs[0], qs[-1] = -1e-12, 1.0 + 1e-12
    idx = np.clip(np.searchsorted(qs, conf, side="right") - 1, 0, n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        m = idx == b
        if m.sum():
            ece += (m.sum() / len(conf)) * abs(float(soft[m].mean()) - float(conf[m].mean()))
    return float(ece)

def quantile_variant(conf_h, soft_h, conf_e, soft_e, seed=SEED):
    point = ece_quantile(conf_h, soft_h) - ece_quantile(conf_e, soft_e)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(2000):
        ih = rng.integers(0, len(conf_h), len(conf_h)); ie = rng.integers(0, len(conf_e), len(conf_e))
        boots.append(ece_quantile(conf_h[ih], soft_h[ih]) - ece_quantile(conf_e[ie], soft_e[ie]))
    return {"ece_hard": ece_quantile(conf_h, soft_h), "ece_easy": ece_quantile(conf_e, soft_e),
            "raw_delta": point, "ci_percentile": [float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))]}

def jsonable(o):
    if isinstance(o, dict): return {k: jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [jsonable(v) for v in o]
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.bool_,)): return bool(o)
    return o

results = {"passes": {}}
pass_data = {}
for name in ["A", "B", "C"]:
    if not (REP / "raw" / f"pass{name}").is_dir():
        continue
    recs = load_pass(name)
    if len(recs) != 1500:
        print(f"pass {name}: only {len(recs)} complete items — skipped for now", flush=True)
        results["passes"][name] = {"n_items": len(recs), "incomplete": True}
        continue
    out = {"n_items": len(recs),
           "models": {}}
    for r in recs.values():
        out["models"][r["model_returned"]] = out["models"].get(r["model_returned"], 0) + 1
    data = {}
    for tier in ("easy", "hard"):
        ids, probs, dist, maj = arrays(recs, tier)
        soft = M.soft_correctness(probs, dist)
        data[tier] = (ids, probs, dist, maj, soft)
        ece_m = M.expected_calibration_error(probs, maj, n_bins=10, strategy="uniform", correctness=soft)
        out[f"ece_{tier}_metrics_binning"] = float(ece_m.ece)
    ph, pe = data["hard"][1], data["easy"][1]
    sh, se = data["hard"][4], data["easy"][4]
    blk = corrected_block(ph, sh, pe, se)
    out["power_binning"] = {k: blk[k] for k in
        ("ece_easy", "ece_hard", "raw_delta_ece", "e0_easy", "e0_hard",
         "bias0_delta_ece", "corrected_delta_ece", "ci_low", "ci_high", "p_value", "n_null_extreme")}
    out["mean_conf"] = {"easy": float(pe.max(axis=1).mean()), "hard": float(ph.max(axis=1).mean())}
    out["mean_agreement"] = {"easy": float(se.mean()), "hard": float(sh.mean())}
    results["passes"][name] = out
    pass_data[name] = data
    print(name, json.dumps(jsonable(out), indent=1)[:800], flush=True)

# Primary pass A: metrics delta_ece block (his _delta_block equivalent, n_boot=10000)
data = pass_data["A"]
ph, yh, sh = data["hard"][1], data["hard"][3], data["hard"][4]
pe, ye, se = data["easy"][1], data["easy"][3], data["easy"][4]
prim = M.delta_ece(ph, yh, pe, ye, seed=SEED, n_boot=10000, n_bins=10,
                   strategy="uniform", ci_method="bca", correctness_hard=sh, correctness_easy=se)
prim_pct = M.delta_ece(ph, yh, pe, ye, seed=SEED, n_boot=10000, n_bins=10,
                       strategy="uniform", ci_method="percentile", correctness_hard=sh, correctness_easy=se)
results["passA_metrics_block"] = {
    "ece_easy": float(prim.ece_easy.ece), "ece_hard": float(prim.ece_hard.ece),
    "raw_delta": float(prim.point),
    "ci_bca": [float(prim.ci_bca_low), float(prim.ci_bca_high)],
    "ci_percentile": [float(prim_pct.ci_percentile_low), float(prim_pct.ci_percentile_high)]}

# Robustness on pass A
conf_h, conf_e = ph.max(axis=1), pe.max(axis=1)
rob = {}
b15 = corrected_block(ph, sh, pe, se, kappa=20.0, n_bins=15)
rob["uniform15_power"] = {k: b15[k] for k in ("ece_easy", "ece_hard", "raw_delta_ece", "corrected_delta_ece", "ci_low", "ci_high", "bias0_delta_ece")}
rob["quantile10_raw"] = quantile_variant(conf_h, sh, conf_e, se)
for kap in (10.0, 50.0):
    bk = corrected_block(ph, sh, pe, se, kappa=kap)
    rob[f"kappa_{int(kap)}"] = {k: bk[k] for k in ("corrected_delta_ece", "bias0_delta_ece", "e0_easy", "e0_hard", "ci_low", "ci_high")}
rob["no_correction_raw_power"] = {"raw_delta_ece": results["passes"]["A"]["power_binning"]["raw_delta_ece"]}
results["passA_robustness"] = rob

# Cross-pass stability of probabilities (A vs B vs C): argmax flip rate, mean |dconf|
names = [n for n in ["A", "B", "C"] if n in pass_data]
stab = {}
for i in range(len(names)):
    for j in range(i + 1, len(names)):
        a, b = names[i], names[j]
        flips, dconf = [], []
        for tier in ("easy", "hard"):
            pa, pb = pass_data[a][tier][1], pass_data[b][tier][1]
            flips.append(float((pa.argmax(axis=1) != pb.argmax(axis=1)).mean()))
            dconf.append(float(np.abs(pa.max(axis=1) - pb.max(axis=1)).mean()))
        stab[f"{a}_vs_{b}"] = {"argmax_flip_rate_pooled": float(np.mean(flips)), "mean_abs_dconf_pooled": float(np.mean(dconf))}
results["probability_stability"] = stab
cds = [results["passes"][n]["power_binning"]["corrected_delta_ece"] for n in names]
results["corrected_delta_spread"] = {"per_pass": dict(zip(names, cds)),
                                     "min": float(min(cds)), "max": float(max(cds)),
                                     "range": float(max(cds) - min(cds)),
                                     "mean": float(np.mean(cds)), "sd": float(np.std(cds, ddof=1)) if len(cds) > 1 else 0.0}

(REP / "results/analysis.json").write_text(json.dumps(jsonable(results), indent=2) + "\n")
print(json.dumps(jsonable(results), indent=2))
