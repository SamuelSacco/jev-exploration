#!/usr/bin/env python3
"""Setup for independent replication of Khosla EXP-1 (Choice arm).

1. Verify items.jsonl / labels.jsonl SHA-256 against preregistration.lock.json.
2. Reconstruct the 750/750 analysis sets with HIS code
   (jevbench.chaosnli.balanced_analysis_ids over universe.jsonl records)
   and compare to the committed items.jsonl primary sets.
3. Fetch ChaosNLI v1.0 SNLI/MNLI text from his pinned mirrors, verify the
   SHA-256 pins from jevbench.chaosnli, parse with HIS load_chaosnli_jsonl.
4. Emit replication/data/items_full.jsonl (1500 primary items, in
   items.jsonl order, with premise/hypothesis/label_dist/tier) and
   replication/results/setup_verification.json.
No Jev calls. No writes outside replication/.
"""
import hashlib, json, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve()
REP = HERE.parents[1]                      # replication/
JB = HERE.parents[2] / "jevbench"         # jevbench repo root
sys.path.insert(0, str(JB))

import numpy as np
from jevbench import chaosnli as C

def sha256_file(p):  # identical algorithm to jevbench.dataset.sha256_file (pydantic-free import path)
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def sha_ids(ids):
    return hashlib.sha256(("\n".join(sorted(ids)) + "\n").encode()).hexdigest()

out = {}
# --- 1. lock hash verification
lock = json.loads((JB / "preregistration.lock.json").read_text())
items_sha = sha256_file(JB / "datasets/chaosnli/items.jsonl")
labels_sha = sha256_file(JB / "datasets/chaosnli/labels.jsonl")
out["lock"] = {"items_sha256_lock": lock["items_sha256"], "items_sha256_disk": items_sha,
               "items_match": lock["items_sha256"] == items_sha,
               "labels_sha256_lock": lock["labels_sha256"], "labels_sha256_disk": labels_sha,
               "labels_match": lock["labels_sha256"] == labels_sha,
               "model_lock": lock["model"], "locked_at": lock["locked_at"]}

# --- committed primary sets
def read_jsonl(p):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

items_rows = read_jsonl(JB / "datasets/chaosnli/items.jsonl")
labels = {r["id"]: r for r in read_jsonl(JB / "datasets/chaosnli/labels.jsonl")}
primary = [r for r in items_rows if r.get("role") == "primary"]
committed = {"easy": sorted(r["id"] for r in primary if r["tier"] == "easy"),
             "hard": sorted(r["id"] for r in primary if r["tier"] == "hard")}
out["committed_counts"] = {k: len(v) for k, v in committed.items()}
out["committed_idset_sha256"] = {k: sha_ids(v) for k, v in committed.items()}
out["n_paraphrase_rows"] = len(items_rows) - len(primary)

# --- 2. reconstruct with his code from universe.jsonl
universe = read_jsonl(JB / "datasets/chaosnli/universe.jsonl")
records = [{"id": r["id"], "entropy": float(r["entropy"])} for r in universe]
ent = np.array([r["entropy"] for r in records])
q_easy, q_hard = C.quantile_thresholds(ent)
out["thresholds_recomputed"] = {"q_easy": q_easy, "q_hard": q_hard,
    "match_thresholds_json": None}
thr = json.loads((JB / "datasets/chaosnli/thresholds.json").read_text())
out["thresholds_recomputed"]["match_thresholds_json"] = (
    q_easy == thr["q_easy"] and q_hard == thr["q_hard"])
recon = C.balanced_analysis_ids(records, q_easy=q_easy, q_hard=q_hard)
out["recon_counts"] = {"easy": len(recon["easy_ids"]), "hard": len(recon["hard_ids"]),
                       "n_easy_pool": recon["n_easy_pool"], "n_hard_pool": recon["n_hard_pool"]}
out["recon_idset_sha256"] = {"easy": sha_ids(recon["easy_ids"]), "hard": sha_ids(recon["hard_ids"])}
out["recon_equals_committed"] = {
    "easy": sorted(recon["easy_ids"]) == committed["easy"],
    "hard": sorted(recon["hard_ids"]) == committed["hard"]}
uni_analysis = {"easy": sorted(r["id"] for r in universe if r["in_analysis"] and r["stratum"] == "easy"),
                "hard": sorted(r["id"] for r in universe if r["in_analysis"] and r["stratum"] == "hard")}
out["universe_in_analysis_equals_committed"] = {
    k: uni_analysis[k] == committed[k] for k in ("easy", "hard")}

# --- 3. fetch ChaosNLI text (his mirrors + pins), parse with his loader
data = REP / "data"; data.mkdir(exist_ok=True)
def fetch(url, dest, pin):
    if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest() == pin:
        return "cached-pin-ok"
    req = urllib.request.Request(url, headers={"User-Agent": "jevbench-fetch/0.1 (research; ChaosNLI v1.0 pin)"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        blob = resp.read()
    got = hashlib.sha256(blob).hexdigest()
    if got != pin:
        raise SystemExit(f"SHA mismatch for {url}: got {got}, pin {pin}")
    dest.write_bytes(blob)
    return "downloaded-pin-ok"

snli_p, mnli_p = data / "chaosNLI_snli.jsonl", data / "chaosNLI_mnli_m.jsonl"
out["fetch"] = {"snli": fetch(C.MIRROR_SNLI, snli_p, C.SNLI_SHA256),
                "mnli": fetch(C.MIRROR_MNLI, mnli_p, C.MNLI_SHA256),
                "snli_sha256": C.SNLI_SHA256, "mnli_sha256": C.MNLI_SHA256}
pop = C.load_population(snli_p, mnli_p)   # his loader: validates counts/entropy
text = {r["id"]: r for r in pop}
out["population_n"] = len(pop)

# --- 4. emit full items in items.jsonl primary order
full, missing = [], []
for r in primary:
    iid = r["id"]; hit = text.get(iid)
    if hit is None:
        missing.append(iid); continue
    lab = labels[iid]
    assert lab["label_dist"] == hit["label_dist"], iid
    full.append({"id": iid, "tier": r["tier"], "source": r["state"]["source"],
                 "premise": hit["premise"], "hypothesis": hit["hypothesis"],
                 "label_dist": lab["label_dist"], "label_count": lab["label_count"],
                 "majority_label": lab["label"]})
out["full_items"] = len(full); out["missing_text"] = missing
with (data / "items_full.jsonl").open("w") as f:
    for r in full:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# exact question construction from his YAML (system python has pyyaml; venv does not)
import subprocess
spec = json.loads(subprocess.check_output(
    ["/usr/bin/python3", "-c",
     "import yaml,json,sys; print(json.dumps(yaml.safe_load(open(sys.argv[1]).read())))",
     str(JB / "experiments/exp1_difficulty_calibration.yaml")]).decode())
rel = spec["questions"]["relation"]
out["choice_question"] = {"instructions": rel["instructions"], "criteria": rel["criteria"],
                          "model_yaml": spec["model"], "repeats_yaml": spec["repeats"]}
(REP / "results/setup_verification.json").write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
