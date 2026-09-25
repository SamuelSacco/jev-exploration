"""Import BBQ into this repo's item shape, preserving the slices that matter.

    python3 lab/corpora/bbq.py --src ~/BBQ/data --out lab/corpora/bbq.jsonl
    python3 lab/corpora/bbq.py --self-test

Downloads nothing. This repo's only approved endpoint is Jev's, so point --src
at a copy of BBQ you already have: the directory of per-category `.jsonl` files
the benchmark ships, or a single such file.

## What BBQ is, and the one thing an importer must not lose

Each question comes in two context conditions over the same two people:

  ambig     the context does not say who did the thing. The correct answer is
            the UNKNOWN option, and anything else is an unsupported guess.
  disambig  the context settles it. The correct answer is a named person.

That pairing is the whole instrument. Accuracy pooled across both conditions
means almost nothing, because the two measure different capabilities: refusing
to guess, and reading. Every downstream number here is reported per condition.

The second thing to preserve is the DIRECTION of a wrong answer on ambiguous
items. `additional_metadata.stereotyped_groups` names the group the item's
stereotype points at, and `answer_info` maps each option to its group. An
unsupported guess that names the stereotyped group is a different event from one
that names the other person, and the difference is the bias signal. An importer
that keeps only (question, options, gold) throws that away and cannot be used
for the claim it is being imported for.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "bbq_sample.jsonl")

UNKNOWN_MARKERS = (
    "unknown", "cannot be determined", "can't be determined", "not enough info",
    "not known", "not enough information", "undetermined", "cannot answer",
    "can't answer", "not answerable",
)

REQUIRED = ("context", "question", "ans0", "ans1", "ans2", "label", "context_condition")


def is_unknown(text: str) -> bool:
    return text.strip().lower().lstrip("the ").strip() in UNKNOWN_MARKERS or any(
        marker in text.strip().lower() for marker in UNKNOWN_MARKERS
    )


def option_groups(row: dict) -> dict:
    """{option index: group label} from answer_info, which BBQ ships per row."""
    info = row.get("answer_info") or {}
    out = {}
    for i in range(3):
        entry = info.get(f"ans{i}")
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            out[i] = entry[1]
        else:
            out[i] = None
    return out


def convert(row: dict, index: int) -> dict:
    missing = [k for k in REQUIRED if k not in row]
    if missing:
        raise ValueError(f"row {index} is missing {missing}; BBQ's schema may have moved")

    options = {f"ans{i}": row[f"ans{i}"] for i in range(3)}
    groups = option_groups(row)
    unknown_index = next(
        (i for i in range(3) if is_unknown(row[f"ans{i}"])), None
    )
    stereotyped = set(row.get("additional_metadata", {}).get("stereotyped_groups") or [])
    stereotype_index = next(
        (i for i, g in groups.items() if g and g in stereotyped and i != unknown_index),
        None,
    )
    ambiguous = row["context_condition"] == "ambig"
    return {
        "id": f"bbq{row.get('example_id', index):06d}",
        "source": "BBQ",
        "category": row.get("category"),
        "condition": "ambiguous" if ambiguous else "disambiguated",
        "polarity": row.get("question_polarity"),
        "text": f"{row['context']}\n\n{row['question']}",
        "context": row["context"],
        "question": row["question"],
        "options": options,
        "gold": f"ans{row['label']}",
        "unknown_option": f"ans{unknown_index}" if unknown_index is not None else None,
        "stereotype_option": f"ans{stereotype_index}" if stereotype_index is not None else None,
        "groups": {f"ans{i}": groups[i] for i in range(3)},
        # On an ambiguous item the correct answer IS the unknown option, so
        # abstention and accuracy are the same event; downstream code should not
        # count them twice.
        "abstention_is_correct": ambiguous,
    }


def load(src: str) -> list:
    paths = (
        sorted(glob.glob(os.path.join(src, "*.jsonl")))
        if os.path.isdir(src)
        else [src]
    )
    if not paths:
        raise FileNotFoundError(f"no .jsonl files under {src}")
    rows = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            for index, line in enumerate(fh):
                line = line.strip()
                if line:
                    rows.append(convert(json.loads(line), index))
    return rows


def summarise(rows: list) -> dict:
    conditions = {}
    for row in rows:
        block = conditions.setdefault(
            row["condition"], {"n": 0, "with_unknown_option": 0, "with_stereotype_option": 0}
        )
        block["n"] += 1
        block["with_unknown_option"] += bool(row["unknown_option"])
        block["with_stereotype_option"] += bool(row["stereotype_option"])
    return {
        "n": len(rows),
        "conditions": conditions,
        "categories": sorted({r["category"] for r in rows if r["category"]}),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", help="BBQ .jsonl file or directory of them")
    ap.add_argument("--out", default=os.path.join(HERE, "bbq.jsonl"))
    ap.add_argument("--self-test", action="store_true",
                    help="import the bundled fixture and print the summary")
    args = ap.parse_args(argv)

    src = FIXTURE if args.self_test else args.src
    if not src:
        print("Pass --src, or --self-test to run against the bundled fixture.",
              file=sys.stderr)
        return 2

    rows = load(src)
    summary = summarise(rows)
    print(f"{summary['n']} items from {src}")
    for condition, block in sorted(summary["conditions"].items()):
        print(
            f"  {condition:<15} n={block['n']:<6} "
            f"unknown option present {block['with_unknown_option']}/{block['n']}, "
            f"stereotype option identified {block['with_stereotype_option']}/{block['n']}"
        )
    print(f"  categories: {', '.join(summary['categories'])}")

    if args.self_test:
        return 0

    with open(args.out, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
