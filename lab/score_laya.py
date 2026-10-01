"""Score a Laya fixture run against Jev recomputed from committed raw.

    python3 lab/score_laya.py lab/runs/<stamp>-laya-all.jsonl

Both arms are scored by the same code (jevlab.stats): accuracy with a
Wilson interval, ECE beside its simulated noise floor, Brier, and the
hit rate at p>=0.9 with its coverage. The Jev arm is never copied from
prose: tiers come from lab/tiers/analyse.read_pass over the committed
20260918T013027Z run (3 passes, metrics averaged across passes),
domains from the committed 20260924T234425Z transfer runs (rep 0),
negation from the committed 20260918T014148Z run (single pass).
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jevlab.stats import brier, coverage_at, ece_with_floor, wilson  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(BASE, "runs")


def metrics(pairs: list) -> dict:
    """pairs: list of (p, gold_bool)."""
    n = len(pairs)
    hits = sum(1 for p, g in pairs if (p >= 0.5) == g)
    lo, hi = wilson(hits, n)
    e = ece_with_floor(pairs)
    cov = coverage_at(pairs, 0.9)
    return {
        "n": n, "acc": hits / n, "acc_ci": [round(lo, 3), round(hi, 3)],
        "ece": round(e["ece"], 4), "floor": round(e["floor_mean"], 4),
        "ratio": round(e["ratio"], 2),
        "brier": round(brier(pairs), 4),
        "cov90": round(cov["coverage"], 3), "hit90": cov["hit_rate"],
    }


def jev_pairs() -> dict:
    """{(dataset, group): [(p, gold), ...]} from committed raw runs."""
    out = {}
    # tiers: 3 passes; keep passes separate, caller averages metrics
    from lab.tiers.analyse import read_pass
    from lab.tiers.baselines import load as load_tiers
    gold = {it["id"]: bool(it["is_phishing"]) for it in load_tiers()}
    tier_of = {}
    with open(os.path.join(BASE, "tiers", "dataset.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            it = json.loads(line)
            tier_of[it["id"]] = it["tier"]
    passes = {}
    for tier in ("t1_trivial", "t2_ordinary", "t3_hard", "t4_adversarial"):
        for idx in range(3):
            passes.setdefault(("tiers", tier), []).append(
                read_pass("20260918T013027Z", tier, idx, gold))
    out.update(passes)
    # domains: transfer runs, rep 0. Item ids are unique only within a
    # slice (code000 exists in both code_security and code_security_rare
    # with different texts and golds), so everything keys on (slice, id)
    # and the slice comes from the run filename, not the item.
    dom_gold = {}
    with open(os.path.join(BASE, "domains", "dataset.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            it = json.loads(line)
            dom_gold[(it["slice"], it["id"])] = bool(it["is_positive"])
    dom = {}
    for path in glob.glob(os.path.join(RUNS, "20260924T234425Z-transfer-*.jsonl")):
        slice_name = os.path.basename(path).split("-transfer-")[1].split(".jsonl")[0]
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                if rec["rep"] != 0:
                    continue
                for qid, ans in rec["response"]["answers"].items():
                    dom.setdefault(("domains", slice_name), []).append(
                        (ans["noul"], dom_gold[(slice_name, qid)]))
    out.update(dom)
    # negation: single committed run
    with open(os.path.join(RUNS, "20260918T014148Z-negation.jsonl"), encoding="utf-8") as fh:
        rec = json.loads(fh.readline())
    from lab.exp_laya import load_fixture
    neg_gold = {it["id"]: it["gold"] for it in load_fixture("negation")}
    out[("negation", "negation")] = [
        (ans["noul"], neg_gold[qid])
        for qid, ans in rec["response"]["answers"].items()
    ]
    return out


def main(argv=None) -> int:
    path = argv[1] if len(argv) > 1 else None
    if not path:
        print("usage: score_laya.py <laya-run.jsonl>")
        return 2
    laya_groups = {}
    lat = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["noul"] is None:
                continue
            key = (rec["dataset"], rec["group"])
            laya_groups.setdefault(key, []).append((rec["noul"], rec["gold"]))
            lat.setdefault(rec["dataset"], []).append(rec["elapsed_s"])
    jev = jev_pairs()
    report = {}
    print(f"{'group':28s} {'arm':5s} {'n':>4s} {'acc':>6s} {'ECE':>7s} {'floor':>6s} "
          f"{'ratio':>5s} {'brier':>6s} {'cov.9':>5s} {'hit.9':>6s}")
    for key in sorted(set(laya_groups) | set(jev)):
        entry = {}
        if key in laya_groups:
            m = metrics(laya_groups[key])
            entry["laya"] = m
            print(f"{key[0]+'/'+key[1]:28s} {'laya':5s} {m['n']:4d} {m['acc']:6.3f} "
                  f"{m['ece']:7.4f} {m['floor']:6.4f} {m['ratio']:5.2f} {m['brier']:6.4f} "
                  f"{m['cov90']:5.2f} {m['hit90'] if m['hit90'] is not None else float('nan'):6.3f}")
        if key in jev:
            val = jev[key]
            if key[0] == "tiers":  # list of 3 passes -> average the metrics
                ms = [metrics(p) for p in val]
                m = {k: (round(sum(x[k] for x in ms) / len(ms), 4)
                         if isinstance(ms[0][k], float) else ms[0][k])
                     for k in ms[0]}
                m["passes"] = 3
            else:
                m = metrics(val)
            entry["jev"] = m
            print(f"{key[0]+'/'+key[1]:28s} {'jev':5s} {m['n']:4d} {m['acc']:6.3f} "
                  f"{m['ece']:7.4f} {m['floor']:6.4f} {m['ratio']:5.2f} {m['brier']:6.4f} "
                  f"{m['cov90']:5.2f} {m['hit90'] if m['hit90'] is not None else float('nan'):6.3f}")
        report[f"{key[0]}/{key[1]}"] = entry
    for ds, xs in sorted(lat.items()):
        xs = sorted(xs)
        report[f"latency/{ds}"] = {
            "n": len(xs), "p50_s": xs[len(xs) // 2],
            "p95_s": xs[int(0.95 * (len(xs) - 1))], "mean_s": round(sum(xs) / len(xs), 4),
        }
        print(f"latency {ds}: n={len(xs)} p50={xs[len(xs)//2]:.3f}s "
              f"p95={xs[int(0.95*(len(xs)-1))]:.3f}s mean={sum(xs)/len(xs):.3f}s")
    out_json = os.path.splitext(path)[0] + "-scores.json"
    def clean(o):  # NaN is not strict JSON; emit null instead
        if isinstance(o, float) and o != o:
            return None
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(v) for v in o]
        return o
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(clean(report), fh, indent=1, sort_keys=True)
    print(f"wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
