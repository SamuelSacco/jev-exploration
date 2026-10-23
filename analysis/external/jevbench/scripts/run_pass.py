#!/usr/bin/env python3
"""Replication driver: one Jev Choice call per item via the connector CLI ONLY.

Usage: run_pass.py --pass-name A [--limit N] [--workers 4]
- Checkpointed: an item whose raw file exists with parsed probabilities is skipped.
- Spend: every CLI invocation (incl. retries) increments replication/spend.json
  under a lock BEFORE the call; hard stop at BUDGET=5000 total calls.
- Raw response saved per item per pass under replication/raw/pass<NAME>/.
Payload mirrors his construction (see REPLICATION.md):
  state = hydrated dict {pair_id, source, text_status:"fetched", premise, hypothesis}
          (same keys/order his runner passes to the SDK), sent as a JSON object
          (API_REFERENCE: state accepts a JSON object).
  model = "jev-1.13.0" (pinned; CLI default jev-latest overridden).
  questions = {"relation": {"type":"choice", instructions, criteria}} FLAT shape
          per connector note. Choice ONLY (his call also bundled 3 Nouls in the
          same request; API evaluates questions in isolation — logged deviation).
"""
import argparse, json, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

REP = Path(__file__).resolve().parents[1]
CLI = Path.home() / "workspace/custom-connectors/custom.legacy-jev/bin/jev.py"
BUDGET = 5000
LABELS = ["entailment", "neutral", "contradiction"]

spend_lock = threading.Lock()
spend_path = REP / "spend.json"

def spend_count():
    try:
        return json.loads(spend_path.read_text())["total_calls"]
    except Exception:
        return 0

def spend_increment(meta):
    with spend_lock:
        cur = spend_count()
        if cur >= BUDGET:
            raise RuntimeError(f"BUDGET EXHAUSTED at {cur}")
        spend_path.write_text(json.dumps({"total_calls": cur + 1}) + "\n")
        with (REP / "spend_log.jsonl").open("a") as f:
            f.write(json.dumps({"n": cur + 1, **meta}) + "\n")
        return cur + 1

def call_jev(payload):
    """One CLI invocation. Returns (ok, response_obj_or_None, stderr)."""
    with _tmp_lock:
        pass
    import tempfile, os
    fd, tmp = tempfile.mkstemp(suffix=".json", dir="/tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, ensure_ascii=False)
        env = dict(os.environ)
        # jev.py inserts a stale templates path; the helper actually lives in
        # .../custom-connector-setup/bin (per CONNECTOR.md). CLI itself unmodified.
        env["PYTHONPATH"] = "/opt/muse/skills/custom-connector-setup/bin" + (
            ":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        r = subprocess.run(["/usr/bin/python3", str(CLI), tmp],
                           capture_output=True, text=True, timeout=120, env=env)
        if r.returncode != 0:
            return False, None, (r.stderr or "")[:500]
        try:
            return True, json.loads(r.stdout), ""
        except Exception as e:
            return False, None, f"unparseable stdout: {e}: {r.stdout[:300]}"
    finally:
        try: os.unlink(tmp)
        except OSError: pass

_tmp_lock = threading.Lock()

def parse_probs(resp):
    try:
        ans = resp["answers"]["relation"]
        probs = ans["probabilities"]
        return {k: float(probs.get(k, 0.0)) for k in LABELS}, ans.get("choice"), resp.get("model")
    except Exception:
        return None, None, (resp.get("model") if isinstance(resp, dict) else None)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pass-name", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    setup = json.loads((REP / "results/setup_verification.json").read_text())
    cq = setup["choice_question"]
    items = [json.loads(l) for l in (REP / "data/items_full.jsonl").read_text().splitlines() if l.strip()]
    if args.limit:
        items = items[: args.limit]
    outdir = REP / "raw" / f"pass{args.pass_name}"
    outdir.mkdir(parents=True, exist_ok=True)

    def fname(iid):
        return outdir / (quote(iid, safe="") + ".json")

    def done(iid):
        p = fname(iid)
        if not p.is_file():
            return False
        try:
            rec = json.loads(p.read_text())
            return rec.get("probabilities") is not None
        except Exception:
            return False

    todo = [it for it in items if not done(it["id"])]
    print(f"pass {args.pass_name}: {len(items)} items, {len(todo)} to call, spend so far {spend_count()}", flush=True)

    def work(it):
        iid = it["id"]
        state = {"pair_id": iid, "source": it["source"], "text_status": "fetched",
                 "premise": it["premise"], "hypothesis": it["hypothesis"]}
        payload = {"state": state, "model": "jev-1.13.0",
                   "questions": {"relation": {"type": "choice",
                                              "instructions": cq["instructions"],
                                              "criteria": cq["criteria"]}}}
        attempts, resp, err = 0, None, ""
        for attempt in (1, 2):
            n = spend_increment({"pass": args.pass_name, "item_id": iid, "attempt": attempt,
                                  "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            attempts = attempt
            ok, resp, err = call_jev(payload)
            if ok:
                break
            # retry once only on transient-looking failures
            low = err.lower()
            if not any(s in low for s in ("500", "502", "503", "504", "429", "timeout", "timed out", "connection", "unparseable")):
                break
            time.sleep(20 if "429" in low else 5)
        probs, choice, model = (parse_probs(resp) if resp is not None else (None, None, None))
        rec = {"item_id": iid, "pass": args.pass_name, "tier": it["tier"],
               "request_payload": payload, "response": resp,
               "probabilities": probs, "choice_returned": choice,
               "model_returned": model, "attempts": attempts, "error": err or None,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        fname(iid).write_text(json.dumps(rec, ensure_ascii=False) + "\n")
        return iid, probs is not None, model

    ok_n, fail = 0, []
    models = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (iid, ok, model) in enumerate(ex.map(work, todo), 1):
            if ok:
                ok_n += 1; models[model] = models.get(model, 0) + 1
            else:
                fail.append(iid)
            if i % 100 == 0:
                print(f"  {i}/{len(todo)} done, ok={ok_n}, spend={spend_count()}", flush=True)
    print(json.dumps({"pass": args.pass_name, "called": len(todo), "ok": ok_n,
                      "failed": fail, "models": models, "spend_total": spend_count()}))
    return 0 if not fail else 2

if __name__ == "__main__":
    raise SystemExit(main())
