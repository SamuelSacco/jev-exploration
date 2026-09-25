"""Score the Jev vs local-4B battery and write the verdict memo.

    python3 analysis/headtohead.py --answers lab/headtohead_answers.json

No API key and no network. Reads what `lab/exp_headtohead.py` wrote, scores the
four preregistered hypotheses, and prints a memo.

Separated from the runner so the verdicts come from committed data and can be
recomputed by anyone, and so the hypotheses cannot be edited once the numbers
are in: they are read back out of the results file, which the runner wrote
before its first call.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jevlab.stats import bootstrap_ci, ece_with_floor, wilson  # noqa: E402
from lab.exp_headtohead import ARMS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ANSWERS = os.path.join(ROOT, "lab", "headtohead_answers.json")


def pairs(block: dict, gold: dict) -> list:
    """(qid, p, gold) triples, sorted by qid.

    The qid is what joins the two arms in the paired statistics: throwing it
    away and zipping by index silently misaligns every pair after a dropped
    item (a local reply that failed to parse drops its qid from the local arm
    but not from the Jev arm).
    """
    return [
        (qid, p, bool(gold[qid]))
        for qid, p in sorted(block.get("probabilities", {}).items())
        if qid in gold
    ]


def _pg(item):
    """(p, gold) out of a pair-row, with or without its qid."""
    return (item[1], item[2]) if len(item) == 3 else (item[0], item[1])


def _hit(p, gold):
    return 1.0 if (p >= 0.5) == gold else 0.0


def _align(a, b):
    """Inner-join two pair lists on qid; return per-pair (hit_a - hit_b) deltas.

    Rows that carry qids (3-tuples from pairs()) are inner-joined on qid, in
    deterministic sorted-qid order: a qid present in only one arm drops its
    pair instead of shifting every later pair. Disjoint qids give no pairs.

    Rows without qids (legacy bare 2-tuples) keep the old truncation/index
    pairing as an explicit fallback -- and it is NOT silent: a stderr warning
    names the misalignment risk every time it actually pairs anything.

    Returns (deltas, used_index_fallback).
    """
    have_qids = (
        bool(a)
        and bool(b)
        and all(len(item) == 3 for item in a)
        and all(len(item) == 3 for item in b)
    )
    if have_qids:
        ja = {qid: (p, gold) for qid, p, gold in a}
        jb = {qid: (p, gold) for qid, p, gold in b}
        deltas = [_hit(*ja[q]) - _hit(*jb[q]) for q in sorted(set(ja) & set(jb))]
        return deltas, False
    n = min(len(a), len(b))
    if n:
        print(
            f"headtohead: pairing {n} items by INDEX (no qids present) -- "
            "a dropped item misaligns every pair after it",
            file=sys.stderr,
        )
    deltas = [_hit(*_pg(a[i])) - _hit(*_pg(b[i])) for i in range(n)]
    return deltas, True


def side_scores(pr: list) -> dict:
    if not pr:
        return {}
    bare = [_pg(row) for row in pr]
    hits = sum(1 for p, gold in bare if _hit(p, gold))
    lo, hi = wilson(hits, len(bare))
    floors = ece_with_floor(bare, trials=300)
    return {
        "n": len(bare),
        "accuracy": round(hits / len(bare), 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "ece": round(floors["ece"], 4),
        "floor": round(floors["floor_mean"], 4),
        "ratio": round(floors["ratio"], 4),
    }


def lexical_bar(arm: str) -> float:
    """The cheap-method floor for an arm, from the committed control scripts."""
    from lab.domains.baselines import lexical, load as load_domains

    if arm == "home_turf":
        rows = [r for r in load_domains() if r["slice"] == "code_security"]
        return round(lexical(rows)["accuracy"], 4)
    if arm in ("adversarial", "typed"):
        # lab/tiers/baselines.py reports the decisive-vocabulary regex per tier.
        from lab.tiers.baselines import DECISIVE_RE, load as load_tiers, score

        rows = [r for r in load_tiers() if r["tier"] == "t4_adversarial"]
        # score() returns one block per tier, keyed by tier name.
        return round(score(rows, DECISIVE_RE)["t4_adversarial"]["rate"], 4)
    # The negation probe is built so that no lexical method beats chance.
    return 0.5


def paired_difference(a, b):
    """Paired bootstrap CI on the accuracy difference, the arms joined on qid.

    Returns (ci95, n_pairs, used_index_fallback). Empty or disjoint arms give
    ([0.0, 0.0], 0, <fallback>).
    """
    deltas, fallback = _align(a, b)
    if not deltas:
        return [0.0, 0.0], 0, fallback
    lo, hi = bootstrap_ci(deltas, statistic=lambda xs: sum(xs) / len(xs))
    return [round(lo, 4), round(hi, 4)], len(deltas), fallback


def difference_ci(a: list, b: list) -> list:
    """Bootstrap interval on the accuracy DIFFERENCE.

    On the difference rather than on each side separately: two overlapping
    independent intervals do not mean the difference covers zero, and reading
    them that way is the mistake this repo's ledger already corrects elsewhere.

    The arms are inner-joined on qid before the paired bootstrap; see _align.
    """
    ci, _, _ = paired_difference(a, b)
    return ci


def verdicts(arms: dict) -> dict:
    out = {}

    def jev(arm):
        return arms.get(arm, {}).get("jev") or {}

    def local(arm):
        return arms.get(arm, {}).get("local") or {}

    # H1
    have = [a for a in ("home_turf", "adversarial", "negation") if jev(a)]
    if len(have) < 3:
        out["H1_jev_clears_the_bar_where_expected"] = {
            "verdict": "UNVERIFIABLE", "why": "needs all three Noul arms"
        }
    else:
        clears = {
            a: jev(a)["ci95"][0] > arms[a]["lexical_bar"]
            for a in ("home_turf", "adversarial", "negation")
        }
        expected = {"home_turf": True, "adversarial": False, "negation": True}
        out["H1_jev_clears_the_bar_where_expected"] = {
            "verdict": "PROVEN" if clears == expected else (
                "REFUTED" if clears["adversarial"] or not clears["negation"] else "PARTIAL"
            ),
            "clears_lexical_bar": clears,
            "expected": expected,
        }

    # H2
    if jev("home_turf") and local("home_turf") and jev("negation") and local("negation"):
        home = local("home_turf")["accuracy"] > jev("home_turf")["accuracy"]
        neg = local("negation")["accuracy"] < jev("negation")["accuracy"]
        out["H2_local_wins_home_turf_and_loses_negation"] = {
            "verdict": "PROVEN" if (home and neg) else ("PARTIAL" if (home or neg) else "REFUTED"),
            "local_wins_home_turf": home,
            "local_loses_negation": neg,
            "home_turf_difference_ci": arms["home_turf"].get("difference_ci"),
            "negation_difference_ci": arms["negation"].get("difference_ci"),
        }
    else:
        out["H2_local_wins_home_turf_and_loses_negation"] = {
            "verdict": "UNVERIFIABLE", "why": "needs both sides on home_turf and negation"
        }

    # H3
    both = [a for a in ARMS if jev(a) and local(a)]
    if not both:
        out["H3_jev_calibrates_better_everywhere"] = {
            "verdict": "UNVERIFIABLE", "why": "needs both sides on at least one arm"
        }
    else:
        better = {a: jev(a)["ratio"] < local(a)["ratio"] for a in both}
        out["H3_jev_calibrates_better_everywhere"] = {
            "verdict": "PROVEN" if all(better.values()) else (
                "REFUTED" if not any(better.values()) else "PARTIAL"
            ),
            "jev_ratio_lower": better,
            "arms_covered": both,
            "incomplete": sorted(set(ARMS) - set(both)),
        }

    # H4
    if jev("typed") and jev("adversarial"):
        ci = arms["typed"].get("vs_adversarial_ci") or [0.0, 0.0]
        gain = jev("typed")["accuracy"] - jev("adversarial")["accuracy"]
        out["H4_choice_beats_noul_on_the_same_items"] = {
            "verdict": "PROVEN" if ci[0] > 0 else ("REFUTED" if ci[0] <= 0 <= ci[1] else "PARTIAL"),
            "accuracy_gain": round(gain, 4),
            "difference_ci95": ci,
        }
    else:
        out["H4_choice_beats_noul_on_the_same_items"] = {
            "verdict": "UNVERIFIABLE", "why": "needs Jev on both typed and adversarial"
        }
    return out


def analyse(doc: dict) -> dict:
    arms = {}
    for name, block in doc.get("arms", {}).items():
        gold = block.get("gold", {})
        jev_pairs = pairs(block.get("jev", {}), gold)
        local_pairs = pairs(block.get("local", {}), gold)
        entry = {
            "n": block.get("n"),
            "primitive": block.get("primitive"),
            "lexical_bar": lexical_bar(name),
            "jev": side_scores(jev_pairs),
            "local": side_scores(local_pairs),
            "local_unparsed": len(block.get("local", {}).get("unparsed", [])),
            "local_latency_p50_s": block.get("local", {}).get("latency_p50_s"),
        }
        if jev_pairs and local_pairs:
            ci, n_pairs, fallback = paired_difference(local_pairs, jev_pairs)
            entry["difference_ci"] = ci
            entry["difference_pairs_n"] = n_pairs
            entry["paired_by"] = "index" if fallback else "qid"
        arms[name] = entry

    if "typed" in arms and "adversarial" in arms:
        typed = pairs(doc["arms"]["typed"].get("jev", {}), doc["arms"]["typed"]["gold"])
        noul = pairs(
            doc["arms"]["adversarial"].get("jev", {}), doc["arms"]["adversarial"]["gold"]
        )
        if typed and noul:
            ci, n_pairs, fallback = paired_difference(typed, noul)
            arms["typed"]["vs_adversarial_ci"] = ci
            arms["typed"]["vs_adversarial_pairs_n"] = n_pairs
            arms["typed"]["vs_adversarial_paired_by"] = "index" if fallback else "qid"

    return {
        "started_at": doc.get("started_at"),
        "transport_jev": doc.get("transport_jev"),
        "transport_local": doc.get("transport_local"),
        "preregistered": doc.get("preregistered"),
        "arms": arms,
        "verdicts": verdicts(arms),
    }


def memo(result: dict) -> str:
    lines = ["# Jev vs local 4B: verdict memo", ""]
    lines.append(f"Run {result['started_at']}.")
    lines.append(f"Jev via `{result['transport_jev']}`, "
                 f"local via `{result['transport_local']}`.")
    lines.append("")
    lines.append("| arm | n | primitive | lexical bar | Jev acc | local acc | Jev ECE/floor | local ECE/floor |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for name in ARMS:
        a = result["arms"].get(name)
        if not a:
            continue
        j, l = a["jev"], a["local"]
        lines.append(
            f"| `{name}` | {a['n']} | {a['primitive']} | {a['lexical_bar']:.1%} | "
            f"{j.get('accuracy', float('nan')):.1%} | "
            f"{l.get('accuracy', float('nan')):.1%} | "
            f"{j.get('ratio', float('nan')):.2f}x | {l.get('ratio', float('nan')):.2f}x |"
        )
    lines.append("")
    lines.append("## Verdicts, against what was written before the run")
    lines.append("")
    for key, block in result["verdicts"].items():
        lines.append(f"**{key}: {block['verdict']}**")
        lines.append("")
        for k, v in block.items():
            if k != "verdict":
                lines.append(f"- {k}: `{v}`")
        lines.append("")
    unparsed = {n: a["local_unparsed"] for n, a in result["arms"].items() if a["local_unparsed"]}
    if unparsed:
        lines.append(
            f"Local replies that did not parse into a probability: `{unparsed}`. "
            "These are dropped, never imputed, so the local n is smaller than the "
            "arm's n wherever this is non-zero."
        )
        lines.append("")
    lines.append(
        "Paired statistics (difference CIs) inner-join the two arms on qid: a "
        "qid present in only one arm drops its pair instead of misaligning every "
        "pair after it. Each entry records how many pairs were used "
        "(`difference_pairs_n` / `vs_adversarial_pairs_n`) and the pairing key "
        "(`paired_by` / `vs_adversarial_paired_by`: `qid`, or `index` for legacy "
        "rows that never carried qids)."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--answers", default=DEFAULT_ANSWERS)
    ap.add_argument("--json", help="write the analysis here")
    ap.add_argument("--memo", help="write the verdict memo here")
    args = ap.parse_args(argv)

    if not os.path.exists(args.answers):
        print(
            f"No answers at {args.answers}.\n"
            "Run the battery first:\n"
            "  python3 lab/exp_headtohead.py --dry-run\n"
            "  JEV_TRANSPORT=... JEV_LOCAL_TRANSPORT=... "
            "python3 lab/exp_headtohead.py --repeat 3",
            file=sys.stderr,
        )
        return 1

    with open(args.answers, encoding="utf-8") as fh:
        doc = json.load(fh)
    result = analyse(doc)
    text = memo(result)
    print(text)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
            fh.write("\n")
    if args.memo:
        with open(args.memo, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"\nWrote {args.memo}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
