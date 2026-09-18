"""Jev lab: support-triage and rerank demos, scored against ground truth.

One API call per demo per pass. Every raw response is written to lab/runs/ before
anything is scored, so a paid call is never lost to a crash in the scoring code and
every published number can be traced back to the response that produced it.

    python3 lab/run_demos.py                 # both demos, one pass
    python3 lab/run_demos.py --repeat 3      # three passes, variance reported
    python3 lab/run_demos.py --only rerank
    python3 lab/run_demos.py --dry-run       # print payloads, make no calls
    python3 lab/run_demos.py --no-floor      # skip the network-floor measurement

Read the caveat in the README before quoting anything this prints. At n=12 and n=8
these results cannot separate Jev from the baselines in lab/baselines.py, which are
printed alongside for exactly that reason.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jevlab.client import JevClient, JevError, measure_network_floor  # noqa: E402
from jevlab.stats import (  # noqa: E402
    accuracy,
    ece_with_floor,
    format_reliability,
    wilson,
)
from lab.baselines import (  # noqa: E402
    URGENCY_RE,
    content_words,
)

BASE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(BASE, "runs")

# Fallback only; the live criteria travel with the labels in tickets.json so the
# answer space and the labels can never drift apart. See lab/LABELS.md.
DEFAULT_DEPT_CRITERIA = {
    "billing": "Payments, invoices, refunds, charges, subscriptions, and disputes about amounts already charged",
    "technical": "Bugs, errors, outages, integrations, crashes, broken features",
    "sales": "Plan comparisons, quotes, discounts, upgrades, pre-purchase questions",
    "other": "Feature requests, product feedback, praise, or anything that is not a failure, a payment matter, or a pre-sale question",
}


# --------------------------------------------------------------------------- demos


def load_tickets(path: str) -> tuple:
    """Return (tickets, criteria, labels_version).

    tickets.json carries its criteria and a labels_version so a run records which
    label set it was scored against; see lab/LABELS.md.
    """
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if isinstance(doc, list):  # v1 files, before the criteria were versioned
        return doc, None, 1
    return doc["tickets"], doc["criteria"]["dept"], doc["labels_version"]


def triage_payload(tickets: list, criteria: dict | None = None) -> tuple:
    state = "Support tickets:\n" + "\n".join(f"[{t['id']}] {t['text']}" for t in tickets)
    questions = {}
    for t in tickets:
        tid = t["id"]
        questions[f"{tid}_dept"] = {
            "type": "choice",
            "instructions": f"Which team should handle ticket {tid}? Judge only this ticket's text.",
            "criteria": dict(criteria or DEFAULT_DEPT_CRITERIA),
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
    return state, questions


def rerank_payload(rr: dict) -> tuple:
    state = (
        "Query: "
        + rr["query"]
        + "\n\nPassages:\n"
        + "\n".join(f"[{p['id']}] {p['text']}" for p in rr["passages"])
    )
    questions = {
        p["id"]: {
            "type": "noul",
            "instructions": (
                f"Is passage {p['id']} relevant for answering the query? Relevant means "
                "it contains information that directly helps answer it."
            ),
            "criteria": {"true": "Relevant to the query", "false": "Not relevant"},
        }
        for p in rr["passages"]
    }
    return state, questions


# -------------------------------------------------------------------------- scoring


def score_triage(resp, tickets: list) -> dict:
    """Score one triage pass. No post-hoc relabelling: the labels are what they are.

    Earlier write-ups of this demo reclassified the two department misses as
    'ambiguous labels' after seeing the answers, which is the same adjudication
    problem this repo criticises elsewhere. If a label is wrong, fix it in
    tickets.json before the run and say so, or leave the miss standing.
    """
    dept_pairs, urgent_pairs = [], []
    detail = []
    for t in tickets:
        tid = t["id"]
        dept_ok = resp.choice(f"{tid}_dept") == t["dept"]
        dept_pairs.append((resp.confidence(f"{tid}_dept") or 0.0, dept_ok))
        urgent_pairs.append((resp.noul(f"{tid}_urgent"), bool(t["urgent"])))
        detail.append(
            {
                "id": tid,
                "dept_pred": resp.choice(f"{tid}_dept"),
                "dept_gold": t["dept"],
                "dept_confidence": round(resp.confidence(f"{tid}_dept") or 0.0, 3),
                "urgent_p": round(resp.noul(f"{tid}_urgent"), 3),
                "urgent_gold": t["urgent"],
                "frustration_pred": round(resp.score(f"{tid}_frustration"), 2),
                "frustration_gold": t["frustration"],
            }
        )
    frust_err = statistics.mean(
        abs(resp.score(f"{t['id']}_frustration") - t["frustration"]) for t in tickets
    )
    dept_hits = sum(1 for _, ok in dept_pairs if ok)
    urgent_hits = sum(1 for p, gold in urgent_pairs if (p >= 0.5) == gold)
    return {
        "dept": _proportion(dept_hits, len(tickets)),
        "urgent": _proportion(urgent_hits, len(tickets)),
        "frustration_mean_abs_error": round(frust_err, 3),
        "dept_confidence_pairs": dept_pairs,
        "urgent_pairs": urgent_pairs,
        "detail": detail,
    }


def score_rerank(resp, rr: dict) -> dict:
    pairs = [(resp.noul(p["id"]), bool(p["relevant"])) for p in rr["passages"]]
    hits = sum(1 for p, gold in pairs if (p >= 0.5) == gold)
    ranked = sorted(rr["passages"], key=lambda p: resp.noul(p["id"]), reverse=True)
    return {
        "relevance": _proportion(hits, len(pairs)),
        "relevant_in_top4": sum(1 for p in ranked[:4] if p["relevant"]),
        "pairs": pairs,
        "ranking": [
            {"id": p["id"], "p": round(resp.noul(p["id"]), 3), "relevant": p["relevant"]}
            for p in ranked
        ],
    }


def _proportion(hits: int, n: int) -> dict:
    lo, hi = wilson(hits, n)
    return {
        "hits": hits,
        "n": n,
        "rate": round(hits / n, 4),
        "ci95": [round(lo, 4), round(hi, 4)],
    }


# ------------------------------------------------------------------------ baselines


def triage_baselines(tickets: list) -> dict:
    urgent_hits = sum(bool(URGENCY_RE.search(t["text"])) == t["urgent"] for t in tickets)
    counts: dict = {}
    for t in tickets:
        counts[t["dept"]] = counts.get(t["dept"], 0) + 1
    return {
        "urgency_keyword_regex": _proportion(urgent_hits, len(tickets)),
        "dept_majority_class": _proportion(max(counts.values()), len(tickets)),
    }


def rerank_baselines(rr: dict) -> dict:
    qw = content_words(rr["query"])
    hits = sum(
        (len(qw & content_words(p["text"])) >= 2) == p["relevant"] for p in rr["passages"]
    )
    return {"word_overlap": _proportion(hits, len(rr["passages"]))}


# -------------------------------------------------------------------------- variance


def variance(passes: list, qids: list, getter) -> dict:
    """How much the same question moves between identical passes.

    A single pass hides this entirely. jev-spam-eval reports that scores near 0.5
    shift between runs and jev-phishing-bench measured 2.2% label flips, so a
    point estimate from one pass overstates what it knows.
    """
    if len(passes) < 2:
        return {"passes": len(passes), "note": "need --repeat 2 or more"}
    diffs, flips = [], 0
    for qid in qids:
        values = [getter(p, qid) for p in passes]
        diffs.append(max(values) - min(values))
        if len({v >= 0.5 for v in values}) > 1:
            flips += 1
    return {
        "passes": len(passes),
        "questions": len(qids),
        "label_flip_rate": round(flips / len(qids), 4),
        "mean_abs_spread": round(statistics.mean(diffs), 4),
        "max_abs_spread": round(max(diffs), 4),
    }


# ------------------------------------------------------------------------- plumbing


def record(name: str, resp, started_at: str) -> None:
    """Append the full raw response before scoring touches it."""
    os.makedirs(RUNS_DIR, exist_ok=True)
    path = os.path.join(RUNS_DIR, f"{started_at}-{name}.jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "task": name,
                    "requested_at": resp.requested_at,
                    "model": resp.model,
                    "elapsed_s": round(resp.elapsed_s, 4),
                    "attempts": resp.attempts,
                    "usage": resp.usage,
                    "response": resp.raw,
                },
                sort_keys=True,
            )
            + "\n"
        )


def calibration_block(pairs: list, label: str) -> dict:
    """ECE next to the noise floor for this sample size. See docs/claims-audit.md §6."""
    block = ece_with_floor(pairs, trials=500)
    return {
        "label": label,
        "n": block["n"],
        "ece": round(block["ece"], 4),
        "noise_floor_mean": round(block["floor_mean"], 4),
        "noise_floor_p95": round(block["floor_p95"], 4),
        "ratio_to_floor": round(block["ratio"], 2),
        "informative": block["informative"],
        "accuracy": round(accuracy(pairs), 4),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repeat", type=int, default=1, help="passes per demo (default 1)")
    ap.add_argument("--only", choices=["triage", "rerank"], help="run one demo")
    ap.add_argument("--dry-run", action="store_true", help="print payloads, make no calls")
    ap.add_argument("--no-floor", action="store_true", help="skip the network-floor probe")
    args = ap.parse_args(argv)

    tickets, criteria, labels_version = load_tickets(os.path.join(BASE, "tickets.json"))
    rr = json.load(open(os.path.join(BASE, "rerank.json"), encoding="utf-8"))

    demos = {
        "triage": (triage_payload(tickets, criteria), lambda r: score_triage(r, tickets)),
        "rerank": (rerank_payload(rr), lambda r: score_rerank(r, rr)),
    }
    if args.only:
        demos = {args.only: demos[args.only]}

    if args.dry_run:
        for name, ((state, questions), _) in demos.items():
            print(json.dumps({"demo": name, "state": state, "questions": questions}, indent=2))
        return 0

    started_at = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    client = JevClient()
    results: dict = {
        "started_at": started_at,
        "repeat": args.repeat,
        "labels_version": labels_version,
        "baselines": {"triage": triage_baselines(tickets), "rerank": rerank_baselines(rr)},
    }
    out_path = os.path.join(BASE, "results.json")

    if not args.no_floor:
        try:
            results["network_floor"] = measure_network_floor()
        except OSError as exc:
            results["network_floor"] = {"error": str(exc)}

    for name, ((state, questions), scorer) in demos.items():
        passes, scores = [], []
        for i in range(args.repeat):
            try:
                resp = client.ask(state, questions)
            except JevError as exc:
                results[name] = {"error": str(exc), "completed_passes": len(passes)}
                _write(out_path, results)
                print(f"{name}: {exc}", file=sys.stderr)
                break
            record(name, resp, started_at)  # persist before scoring
            passes.append(resp)
            scores.append(scorer(resp))
            print(
                f"{name} pass {i + 1}/{args.repeat}: {resp.elapsed_s:.2f}s, "
                f"model={resp.model}, attempts={resp.attempts}",
                file=sys.stderr,
            )
        if not passes:
            continue

        first = scores[0]
        block = {
            "model": passes[0].model,
            "usage": passes[0].usage,
            "latency_s": {
                "passes": [round(p.elapsed_s, 3) for p in passes],
                "min": round(min(p.elapsed_s for p in passes), 3),
                "median": round(statistics.median(p.elapsed_s for p in passes), 3),
            },
            "scores": {k: v for k, v in first.items() if not k.endswith("pairs")},
        }
        if name == "triage":
            block["calibration"] = [
                calibration_block(first["urgent_pairs"], "urgency (noul)"),
                calibration_block(first["dept_confidence_pairs"], "department (choice confidence)"),
            ]
            block["variance"] = variance(
                passes,
                [f"{t['id']}_urgent" for t in tickets],
                lambda p, q: p.noul(q),
            )
        else:
            block["calibration"] = [calibration_block(first["pairs"], "relevance (noul)")]
            block["variance"] = variance(
                passes, [p["id"] for p in rr["passages"]], lambda p, q: p.noul(q)
            )
        results[name] = block
        _write(out_path, results)  # checkpoint after every demo

    _report(results)
    return 0


def _write(path: str, results: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
        fh.write("\n")


def _report(results: dict) -> None:
    print("\n=== summary ===")
    for name in ("triage", "rerank"):
        block = results.get(name)
        if not block or "error" in block:
            continue
        print(f"\n{name} (model {block['model']}, median {block['latency_s']['median']}s)")
        for key, val in block["scores"].items():
            if isinstance(val, dict) and "ci95" in val:
                lo, hi = val["ci95"]
                print(
                    f"  {key:<24} {val['hits']}/{val['n']}  "
                    f"({val['rate']:.1%})  CI [{lo:.1%}, {hi:.1%}]"
                )
        for cal in block["calibration"]:
            verdict = "informative" if cal["informative"] else "at the noise floor"
            print(
                f"  calibration {cal['label']:<32} ECE {cal['ece']:.3f} "
                f"vs floor {cal['noise_floor_mean']:.3f} "
                f"({cal['ratio_to_floor']}x, {verdict})"
            )
    print("\nbaselines on the same data:")
    for demo, blocks in results["baselines"].items():
        for key, val in blocks.items():
            lo, hi = val["ci95"]
            print(
                f"  {demo}/{key:<26} {val['hits']}/{val['n']}  "
                f"({val['rate']:.1%})  CI [{lo:.1%}, {hi:.1%}]"
            )
    floor = results.get("network_floor", {})
    if "p50_s" in floor:
        print(f"\nnetwork floor to {floor['host']}: p50 {floor['p50_s']:.3f}s")
        print("Subtract this before comparing latency against TypeSafe's service-time claim.")
    print("\nRaw responses in lab/runs/. Overlapping intervals mean the demo did not")
    print("separate Jev from the baseline; see the README caveat.")


if __name__ == "__main__":
    raise SystemExit(main())
