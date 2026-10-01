"""T2 control: Jev per-item (bare single-item states, exactly what the
Laya arm received) on the diagnostic subset, via the workspace skill CLI.
Subset: t1 items[:20]+[100:120] (the phrasing-diagnostic 40), first 10
items per domains slice, all 80 negation items. Raw responses cached. Output committed as
lab/runs/20261001T181500Z-jev-peritem.jsonl.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, "/home/hatch/workspace/jev-laya-work")
from lab.exp_laya import load_fixture  # noqa: E402

JEV_CLI = os.path.expanduser("~/workspace/skills/jev/bin/jev.py")
OUT = os.path.expanduser("~/workspace/laya-runs/t2-jev-peritem.jsonl")
CACHE = os.path.expanduser("~/workspace/laya-runs/t2-cache")
os.makedirs(CACHE, exist_ok=True)

tiers = [i for i in load_fixture("tiers") if i["group"] == "t1_trivial"]
subset = tiers[:20] + tiers[100:120]
doms = load_fixture("domains")
seen = {}
for it in doms:
    seen.setdefault(it["group"], []).append(it)
for g, xs in seen.items():
    subset += xs[:10]
subset += load_fixture("negation")
print("subset:", len(subset), flush=True)

done = set()
if os.path.exists(OUT):
    done = {json.loads(l)["uid"] for l in open(OUT)}
fh = open(OUT, "a")
for it in subset:
    uid = f"{it['dataset']}/{it['group']}/{it['id']}"
    if uid in done:
        continue
    cache_path = os.path.join(CACHE, uid.replace("/", "_") + ".json")
    if os.path.exists(cache_path):
        resp = json.load(open(cache_path))
    else:
        payload = {"state": it["state"], "model": "jev-latest",
                   "questions": {"q": it["question"]}}
        pf = cache_path + ".payload.json"
        json.dump(payload, open(pf, "w"))
        out = subprocess.run([sys.executable, JEV_CLI, pf],
                             capture_output=True, text=True, timeout=120)
        os.unlink(pf)
        if out.returncode != 0:
            print("FAIL", uid, out.stderr[-200:], flush=True)
            continue
        resp = json.loads(out.stdout)
        json.dump(resp, open(cache_path, "w"))
    ans = resp["answers"]["q"]
    fh.write(json.dumps({"uid": uid, "dataset": it["dataset"], "group": it["group"],
                         "id": it["id"], "gold": it["gold"], "noul": ans.get("noul"),
                         "model": resp.get("model"),
                         "input_tokens": (resp.get("usage") or {}).get("input_tokens")},
                        sort_keys=True) + "\n")
    fh.flush()
fh.close()
print("T2-DONE")
