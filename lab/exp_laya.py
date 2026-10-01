"""Run Laya over this repo's committed Noul fixtures (issue: Laya evaluation).

    python3 lab/exp_laya.py --dataset tiers --limit 20     # pilot
    python3 lab/exp_laya.py --dataset all                  # full run

Laya (github.com/NandhaKishorM/laya, Apache-2.0) mirrors Jev's
{state, questions} interface, so each fixture item is scored with the
*identical* question payload the committed Jev runs used — same
instructions, same criteria, no tuning, no per-task training. The
states differ in two ways, both forced by the English checkpoint's
512-token window and both disclosed in lab/laya/FINDINGS.md: Jev
received batched shared states (40 messages per state for tiers,
chunks for domains, all 80 passages for negation), Laya one item per
state; and Jev's per-item state slices carried "[{id}]" markers under
a header, while Laya's states are the bare item text. Results are
reported as per-item-state Laya vs batched-state Jev, with a Jev
per-item control bounding the batching difference.

Requires the `laya` package and a downloaded checkpoint; runs entirely
locally. Raw per-item outputs land in lab/runs/ before scoring, in the
house JSONL shape. Scoring reuses jevlab.stats, and the Jev arm is
recomputed from the committed raw responses, never copied from prose.

Two formulation differences vs the committed Jev runs, both disclosed
in lab/laya/FINDINGS.md: (1) batching — Jev's states held many items at
once, Laya's hold one; the shared state was visible to every Jev
question (claims-audit row 18 isolates *instructions*, not state), so
this is a real confound, bounded by a Jev per-item control run;
(2) state format — Jev's per-item state slices carried "[{id}]" markers
under a header, Laya's states are the bare item text, so the id each
instruction references appears nowhere in Laya's state.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

BASE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(BASE, "runs")

TIER_INSTRUCTIONS = (
    "Is message {id} a phishing or otherwise malicious email, as opposed to a "
    "legitimate one? Judge the message on its own content."
)
TIER_CRITERIA = {
    "true": "Phishing or otherwise malicious",
    "false": "A legitimate message",
}
NEG_CRITERIA = {
    "true": "The passage supports the claim",
    "false": "The passage does not support the claim, or contradicts it",
}
NEG_INSTRUCTIONS = (
    'Does passage {id} support this claim: "{claim}"? '
    "Support means the passage asserts the claim, not merely that it "
    "discusses the same subject."
)


def load_fixture(dataset: str) -> list:
    """Yield dicts: {dataset, group, id, state, question, gold}."""
    items = []
    if dataset in ("tiers", "all"):
        path = os.path.join(BASE, "tiers", "dataset.jsonl")
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                it = json.loads(line)
                items.append({
                    "dataset": "tiers", "group": it["tier"], "id": it["id"],
                    "state": it["text"],
                    "question": {"type": "noul",
                                 "instructions": TIER_INSTRUCTIONS.format(id=it["id"]),
                                 "criteria": dict(TIER_CRITERIA)},
                    "gold": bool(it["is_phishing"]),
                })
    if dataset in ("domains", "all"):
        path = os.path.join(BASE, "domains", "dataset.jsonl")
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                it = json.loads(line)
                items.append({
                    "dataset": "domains", "group": it["slice"], "id": it["id"],
                    "state": it["text"],
                    "question": {"type": "noul",
                                 "instructions": it["question"].format(id=it["id"]),
                                 "criteria": dict(it["criteria"])},
                    "gold": bool(it["is_positive"]),
                })
    if dataset in ("negation", "all"):
        path = os.path.join(BASE, "negation.json")
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        for pair in doc["pairs"]:
            for suffix, key, gold in (("_s", "supports", True), ("_r", "refutes", False)):
                iid = f"{pair['id']}{suffix}"
                items.append({
                    "dataset": "negation", "group": "negation", "id": iid,
                    "state": pair[key],
                    "question": {"type": "noul",
                                 "instructions": NEG_INSTRUCTIONS.format(id=iid, claim=pair["claim"]),
                                 "criteria": dict(NEG_CRITERIA)},
                    "gold": gold,
                })
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="all",
                    choices=["tiers", "domains", "negation", "all"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--checkpoint", default="convaiinnovations/laya")
    ap.add_argument("--out-prefix", default=None)
    ap.add_argument("--resume", action="store_true",
                    help="append to the existing run file, skipping finished ids")
    args = ap.parse_args(argv)

    import laya  # imported here so --help works without the dependency

    items = load_fixture(args.dataset)
    if args.limit:
        items = items[: args.limit]
    stamp = args.out_prefix or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    os.makedirs(RUNS_DIR, exist_ok=True)
    out_path = os.path.join(RUNS_DIR, f"{stamp}-laya-{args.dataset}.jsonl")

    done = set()
    if args.resume and os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                # (dataset, group, id): domains ids repeat across slices
                done.add((rec["dataset"], rec["group"], rec["id"]))
        items = [it for it in items
                 if (it["dataset"], it["group"], it["id"]) not in done]
        print(f"resuming: {len(done)} already done, {len(items)} remaining", flush=True)

    t0 = time.perf_counter()
    agent = laya.load(args.checkpoint)
    load_s = time.perf_counter() - t0
    print(f"checkpoint loaded in {load_s:.1f}s; {len(items)} items", flush=True)

    with open(out_path, "a" if done else "w", encoding="utf-8") as fh:
        for i, it in enumerate(items):
            t = time.perf_counter()
            res = agent.predict(it["state"], {"q": it["question"]})
            elapsed = time.perf_counter() - t
            ans = res["answers"]["q"]
            rec = {
                "dataset": it["dataset"], "group": it["group"], "id": it["id"],
                "gold": it["gold"], "noul": ans.get("noul"),
                "confidence": ans.get("confidence"),
                "elapsed_s": round(elapsed, 4),
                "usage": res.get("usage"),
                "model": res.get("model"),
            }
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
            fh.flush()
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(items)}", flush=True)
    print(f"wrote {out_path} (load {load_s:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
