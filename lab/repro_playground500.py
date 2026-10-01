"""Reproduce the laya-playground 500-example Laya-vs-Jev run (2026-09-20).

Their harness (wdobry/laya-playground, eval/run_eval.py) needs a raw
TYPESAFE_API_KEY, which this environment does not hold; Jev calls here go
through the workspace skill CLI instead. Everything else follows their
protocol exactly: dataset rebuilt by their eval/build_dataset.py (seed 7,
provenance-checked), the identical {state, questions} body to both
models, their read_answer/ece/summarise arithmetic copied verbatim.
Raw responses from both arms are written out (theirs were not committed).

Version deltas vs the original run, disclosed: laya 0.3.22 here vs
0.3.4 then (checkpoints stated unchanged upstream — the English
checkpoint bytes are pinned in the laya repo's verify/checkpoints.json);
Jev model requested as jev-latest here (theirs recorded jev-1.13.0);
Jev latency here includes the CLI subprocess path and is NOT comparable
to their keep-alive HTTPS timing — only accuracy/ECE are reproduced.
Laya latency here is in-process predict() on a 2-core CPU VM, vs their
M1 Max GPU server forward pass.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time

JEV_CLI = os.path.expanduser("~/workspace/skills/jev/bin/jev.py")
JEV_PRICE_PER_MTOK = 0.042


# --- their scoring, copied verbatim from eval/run_eval.py (MIT) ---
def read_answer(a):
    if a["type"] == "noul":
        p = float(a["noul"])
        return p >= 0.5, max(p, 1 - p)
    probs = {k: float(v) for k, v in a["probabilities"].items()}
    top = max(probs, key=probs.get)
    return (int(top) if a["type"] == "score" else top), probs[top]


def ece(conf, correct, bins=10):
    if not conf:
        return None
    total, err = len(conf), 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [i for i, c in enumerate(conf) if (c > lo or b == 0) and c <= hi]
        if sel:
            err += len(sel) / total * abs(sum(conf[i] for i in sel) / len(sel)
                                          - sum(correct[i] for i in sel) / len(sel))
    return err


def summarise(rows, is_score):
    ms = sorted(r["ms"] for r in rows)
    out = {"n": len(rows),
           "accuracy": round(sum(r["correct"] for r in rows) / len(rows), 4),
           "ece": round(ece([r["conf"] for r in rows], [r["correct"] for r in rows]), 4),
           "p50_ms": round(ms[len(ms) // 2], 1),
           "p95_ms": round(ms[int(0.95 * (len(ms) - 1))], 1)}
    if is_score:
        out["within_one_level"] = round(
            sum(abs(r["pred"] - r["label"]) <= 1 for r in rows) / len(rows), 4)
    return out


# --- arms ---
def jev_call(state, questions, cache_path):
    if os.path.exists(cache_path):
        return json.load(open(cache_path))
    payload = {"state": state, "model": "jev-latest", "questions": questions}
    pf = cache_path + ".payload.json"
    with open(pf, "w") as fh:
        json.dump(payload, fh)
    t0 = time.perf_counter()
    out = subprocess.run([sys.executable, JEV_CLI, pf],
                         capture_output=True, text=True, timeout=120)
    ms = (time.perf_counter() - t0) * 1000
    if out.returncode != 0:
        raise RuntimeError(f"jev CLI failed: {out.stderr[-300:]}")
    resp = json.loads(out.stdout)
    rec = {"answers": resp["answers"],
           "meta": {"ms": ms, "input_tokens": (resp.get("usage") or {}).get("input_tokens"),
                    "model": resp.get("model")},
           "raw": resp}
    with open(cache_path, "w") as fh:
        json.dump(rec, fh)
    os.unlink(pf)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--playground", default=os.path.expanduser("~/workspace/laya-playground"))
    ap.add_argument("--out", default=os.path.expanduser("~/workspace/laya-runs/500"))
    ap.add_argument("--tasks", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-jev", action="store_true")
    ap.add_argument("--checkpoint", default=os.path.expanduser("~/workspace/laya-ckpt-en"))
    args = ap.parse_args()

    import laya
    tasks = json.load(open(os.path.join(args.playground, "eval", "tasks.json")))
    only = set(args.tasks.split(",")) if args.tasks else None
    os.makedirs(args.out, exist_ok=True)
    cache = os.path.join(args.out, "jev-cache")
    os.makedirs(cache, exist_ok=True)

    t0 = time.perf_counter()
    agent = laya.load(args.checkpoint)
    print(f"laya loaded in {time.perf_counter() - t0:.1f}s", flush=True)

    report, tokens, jev_model = [], 0, None
    raw_laya = open(os.path.join(args.out, "laya-raw.jsonl"), "a")
    for task in tasks:
        if only and task["id"] not in only:
            continue
        rows = [json.loads(l) for l in open(
            os.path.join(args.playground, "eval", "data", task["id"] + ".jsonl"))]
        if args.limit:
            rows = rows[: args.limit]
        questions = {task["question_id"]: task["question"]}
        agent.predict(rows[0]["text"], questions)  # warm-up, as theirs did
        got = {"laya": [], "jev": []}
        for i, ex in enumerate(rows):
            t = time.perf_counter()
            res = agent.predict(ex["text"], questions)
            ms = (time.perf_counter() - t) * 1000
            a = res["answers"][task["question_id"]]
            raw_laya.write(json.dumps({"task": task["id"], "id": ex["id"], "answer": a,
                                       "ms": ms, "label": ex["label"]}) + "\n")
            raw_laya.flush()
            pred, conf = read_answer(a)
            got["laya"].append({"pred": pred, "label": ex["label"],
                                "correct": pred == ex["label"], "conf": conf, "ms": ms})
            if not args.skip_jev:
                tdir = os.path.join(cache, task["id"])
                os.makedirs(tdir, exist_ok=True)
                rec = jev_call(ex["text"], questions,
                               os.path.join(tdir, f"{ex['id']}.json"))
                ja = rec["answers"][task["question_id"]]
                pred, conf = read_answer(ja)
                got["jev"].append({"pred": pred, "label": ex["label"],
                                   "correct": pred == ex["label"], "conf": conf,
                                   "ms": rec["meta"]["ms"]})
                tokens += rec["meta"].get("input_tokens") or 0
                jev_model = rec["meta"].get("model") or jev_model
            if (i + 1) % 25 == 0:
                print(f"  {task['id']} {i + 1}/{len(rows)}", flush=True)
        is_score = task["question"]["type"] == "score"
        entry = {k: task[k] for k in ("id", "title", "source", "in_laya_training_data")}
        entry.update(type=task["question"]["type"],
                     options=len(task["question"].get("criteria") or [0, 1]),
                     laya=summarise(got["laya"], is_score))
        if not args.skip_jev:
            entry["jev"] = summarise(got["jev"], is_score)
        report.append(entry)
        print("%-18s laya acc %.3f ece %.3f p50 %6.1f ms%s" % (
            task["id"], entry["laya"]["accuracy"], entry["laya"]["ece"],
            entry["laya"]["p50_ms"],
            (" | jev acc %.3f ece %.3f" % (entry["jev"]["accuracy"], entry["jev"]["ece"]))
            if not args.skip_jev else ""), flush=True)
    raw_laya.close()
    n = sum(t["laya"]["n"] for t in report)
    mean = lambda who, key: round(sum(t[who][key] * t[who]["n"] for t in report) / n, 4)
    overall = {"laya": {"accuracy": mean("laya", "accuracy"), "ece": mean("laya", "ece"),
                        "p50_ms": round(statistics.median(t["laya"]["p50_ms"] for t in report), 1)}}
    if not args.skip_jev:
        overall["jev"] = {"accuracy": mean("jev", "accuracy"), "ece": mean("jev", "ece"),
                          "p50_ms": round(statistics.median(t["jev"]["p50_ms"] for t in report), 1)}
    out = {"recorded": time.strftime("%Y-%m-%d"), "examples": n,
           "laya": {"version": laya.__version__, "checkpoint": "english",
                    "where": "local, 2-core CPU VM, in-process predict"},
           "jev": {"model": jev_model, "where": "hosted API via skill CLI",
                   "input_tokens": tokens,
                   "cost_usd": round(tokens / 1e6 * JEV_PRICE_PER_MTOK, 5)},
           "overall": overall, "tasks": report}
    with open(os.path.join(args.out, "versus-repro.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("\noverall", json.dumps(overall))
    print("jev input tokens %d = $%.5f" % (tokens, out["jev"]["cost_usd"]))


if __name__ == "__main__":
    main()
