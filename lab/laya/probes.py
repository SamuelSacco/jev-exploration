"""Mechanism probes for the Laya tiers collapse (diagnostic only).

Variants on the same 40 t1_trivial items (20 phish / 20 legit):
  A_verbatim   the committed Jev payload, full email state (from main run)
  D_subject    state = subject line only, verbatim question
  E_nocriteria full state, instructions only, no criteria dict
Writes JSON to ~/workspace/laya-runs/probes.json.
"""
import json
import sys

sys.path.insert(0, "/home/hatch/workspace/jev-laya-work")
from lab.exp_laya import load_fixture, TIER_CRITERIA  # noqa: E402
import laya  # noqa: E402

items = [i for i in load_fixture("tiers") if i["group"] == "t1_trivial"]
sel = items[:20] + items[100:120]
agent = laya.load("/home/hatch/workspace/laya-ckpt-en")
out = {"golds": [i["gold"] for i in sel], "ids": [i["id"] for i in sel]}


def subject_of(text):
    for line in text.splitlines():
        if line.startswith("Subject:"):
            return line[len("Subject:"):].strip()
    return text[:80]


def run(name, state_fn, question_fn):
    ps = []
    for it in sel:
        r = agent.predict(state_fn(it), {"q": question_fn(it)})
        ps.append(round(r["answers"]["q"]["noul"], 4))
    hits = sum((p >= 0.5) == g for p, g in zip(ps, out["golds"]))
    out[name] = {"acc": hits / len(sel), "mean_p": round(sum(ps) / len(ps), 3), "ps": ps}
    print(name, out[name]["acc"], out[name]["mean_p"], flush=True)


run("D_subject", lambda it: subject_of(it["state"]), lambda it: it["question"])
run("E_nocriteria", lambda it: it["state"],
    lambda it: {"type": "noul", "instructions": it["question"]["instructions"]})
json.dump(out, open("/home/hatch/workspace/laya-runs/probes.json", "w"), indent=1)
print("PROBES-DONE")
