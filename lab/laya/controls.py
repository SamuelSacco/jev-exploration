"""T1 (state format) + T3 (dtype/bf16 formality) + clean latency sample.

T1: Laya on 40 t1 + 40 domains (10/slice) + 80 negation with state =
"[{id}]\\n{text}" — the exact per-item slice of Jev's batched states.
T3a: log agent.dtype / agent.amp_enabled at load.
Latency: 100 playground SMS texts, in-process, uncontended.
Writes ~/workspace/laya-runs/controls.json.
"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, "/home/hatch/workspace/jev-laya-work")
from lab.exp_laya import load_fixture  # noqa: E402
import laya  # noqa: E402

RUNS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs")
STAMP = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())

agent = laya.load("/home/hatch/workspace/laya-ckpt-en")
out = {"dtype": str(getattr(agent, "dtype", "?")),
       "amp_enabled": getattr(agent, "amp_enabled", "?")}

tiers = [i for i in load_fixture("tiers") if i["group"] == "t1_trivial"]
sub = tiers[:20] + tiers[100:120]
doms = load_fixture("domains")
seen = {}
for it in doms:
    seen.setdefault(it["group"], []).append(it)
for g, xs in seen.items():
    sub += xs[:10]
sub += load_fixture("negation")


def score(items, state_fn, peritem):
    hits, ps = 0, []
    for it in items:
        state = state_fn(it)
        r = agent.predict(state, {"q": it["question"]})
        p = r["answers"]["q"]["noul"]
        ps.append(p)
        hits += (p >= 0.5) == it["gold"]
        peritem.append({"id": it["id"], "state": state, "p": p,
                        "pred": p >= 0.5, "gold": bool(it["gold"]),
                        "raw": r["answers"]})
    return {"n": len(items), "acc": hits / len(items),
            "mean_p": round(statistics.mean(ps), 3)}


groups = {}
peritem = []
for name, items in (("t1", sub[:40]), ("domains", sub[40:80]), ("negation", sub[80:])):
    groups[name] = score(items, lambda it: "[%s]\n%s" % (it["id"], it["state"]), peritem)
    print("T1", name, groups[name], flush=True)
out["T1_bracketed_state"] = groups

peritem_path = os.path.join(RUNS, "%s-laya-bracketed-control.jsonl" % STAMP)
os.makedirs(RUNS, exist_ok=True)
with open(peritem_path, "w") as f:
    for rec in peritem:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
print("per-item raw:", peritem_path, len(peritem), flush=True)

texts = []
for line in open("/home/hatch/workspace/laya-playground/eval/data/sms_spam.jsonl"):
    texts.append(json.loads(line)["text"])
q = {"q": {"type": "noul", "instructions": "Is this SMS message spam?"}}
lat = []
for t in texts:
    t0 = time.perf_counter()
    agent.predict(t, q)
    lat.append((time.perf_counter() - t0) * 1000)
lat.sort()
out["latency_sms100_ms"] = {"p50": round(lat[50], 1), "p95": round(lat[95], 1),
                            "mean": round(statistics.mean(lat), 1)}
print("latency", out["latency_sms100_ms"], flush=True)
json.dump(out, open("/home/hatch/workspace/laya-runs/controls.json", "w"), indent=1)
print("CONTROLS-DONE")
