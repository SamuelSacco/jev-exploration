"""Jev claims lab: support-triage + rerank demos, scored against ground truth.

One Jev API call per demo. Uses the bundled jev CLI (skills/jev/bin/jev.py),
which needs a TypeSafe API key — see the repo README.
"""
import json
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
CLI = os.environ.get("JEV_CLI", os.path.join(BASE, "..", "skills", "jev", "bin", "jev.py"))
PAYLOAD = os.path.join(BASE, "_payload.json")


def call(payload):
    with open(PAYLOAD, "w") as fh:
        json.dump(payload, fh)
    t0 = time.time()
    out = subprocess.run([sys.executable, CLI, PAYLOAD], capture_output=True, text=True, timeout=120)
    dt = time.time() - t0
    if out.returncode != 0:
        raise RuntimeError(f"Jev call failed: {out.stderr}")
    return json.loads(out.stdout), dt


results = {}

# ---- Demo 1: triage, 12 tickets x 3 questions, ONE call
tickets = json.load(open(os.path.join(BASE, "tickets.json")))
state = "Support tickets:\n" + "\n".join(f"[{t['id']}] {t['text']}" for t in tickets)
questions = {}
for t in tickets:
    tid = t["id"]
    questions[f"{tid}_dept"] = {
        "type": "choice",
        "instructions": f"Which team should handle ticket {tid}? Judge only this ticket's text.",
        "criteria": {
            "billing": "Payments, invoices, refunds, charges, subscriptions, pricing disputes",
            "technical": "Bugs, errors, outages, integrations, crashes, broken features",
            "sales": "Plan comparisons, quotes, discounts, upgrades, pre-purchase questions",
            "other": "Does not fit any of the above",
        },
    }
    questions[f"{tid}_urgent"] = {
        "type": "noul",
        "instructions": f"Does ticket {tid} convey urgency (blocking issue, time pressure, strong frustration)?",
        "criteria": {"true": "Urgent: needs fast handling", "false": "Not urgent"},
    }
    questions[f"{tid}_frustration"] = {
        "type": "score",
        "instructions": f"How frustrated is the customer in ticket {tid}?",
        "criteria": ["Calm or positive", "Mildly annoyed or concerned", "Angry or very upset"],
    }

resp, dt = call({"state": state, "model": "jev-latest", "questions": questions})
answers = resp["answers"]
correct_dept = sum(1 for t in tickets if answers[f"{t['id']}_dept"]["choice"] == t["dept"])
correct_urg = sum(1 for t in tickets if (answers[f"{t['id']}_urgent"]["noul"] >= 0.5) == t["urgent"])
frust_err = sum(abs(answers[f"{t['id']}_frustration"]["score"] - t["frustration"]) for t in tickets) / len(tickets)
detail = [
    {
        "id": t["id"],
        "dept": [answers[f"{t['id']}_dept"]["choice"], t["dept"]],
        "urgent": [round(answers[f"{t['id']}_urgent"]["noul"], 3), t["urgent"]],
        "frustration": [round(answers[f"{t['id']}_frustration"]["score"], 2), t["frustration"]],
    }
    for t in tickets
]
results["triage"] = {
    "latency_s": round(dt, 2), "usage": resp.get("usage", {}),
    "dept_accuracy": f"{correct_dept}/{len(tickets)}",
    "urgent_accuracy": f"{correct_urg}/{len(tickets)}",
    "frustration_mean_abs_error": round(frust_err, 3),
    "detail": detail,
}

# ---- Demo 2: rerank, 8 passages, ONE call
rr = json.load(open(os.path.join(BASE, "rerank.json")))
state2 = "Query: " + rr["query"] + "\n\nPassages:\n" + "\n".join(f"[{p['id']}] {p['text']}" for p in rr["passages"])
q2 = {
    p["id"]: {
        "type": "noul",
        "instructions": f"Is passage {p['id']} relevant for answering the query? Relevant means it contains information that directly helps answer it.",
        "criteria": {"true": "Relevant to the query", "false": "Not relevant"},
    }
    for p in rr["passages"]
}
resp2, dt2 = call({"state": state2, "model": "jev-latest", "questions": q2})
a2 = resp2["answers"]
ranked = sorted(rr["passages"], key=lambda p: a2[p["id"]]["noul"], reverse=True)
correct_rel = sum(1 for p in rr["passages"] if (a2[p["id"]]["noul"] >= 0.5) == p["relevant"])
top4 = sum(1 for p in ranked[:4] if p["relevant"])
results["rerank"] = {
    "latency_s": round(dt2, 2), "usage": resp2.get("usage", {}),
    "relevance_accuracy": f"{correct_rel}/{len(rr['passages'])}",
    "relevant_in_top4": f"{top4}/4",
    "ranking": [(p["id"], round(a2[p["id"]]["noul"], 3), p["relevant"]) for p in ranked],
}

json.dump(results, open(os.path.join(BASE, "results.json"), "w"), indent=2)
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "detail"} for k, v in results.items()}, indent=2))
