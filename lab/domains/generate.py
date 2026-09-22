"""Generate the cross-domain dataset for issue #9.

Deterministic and seeded, so the committed dataset can be rebuilt byte for byte
and audited by rerunning rather than by trusting the file.

    python3 lab/domains/generate.py --out lab/domains/dataset.jsonl

Issue #9 asks whether the calibration correction fitted on the e-mail difficulty
gradient transfers to other domains. Answering it needs slices that differ from
that gradient in subject matter and in nothing else that matters, so this
generator copies `lab/tiers/generate.py` exactly and changes only the content:

**The label is chosen before the text exists.** A counter decides positive or
negative and the item is then built to match, so the label never depends on
anyone reading the finished text. `analysis/circularity.py` checks this
mechanically for the gradient; `test_domain_labels_are_not_model_derived` does
the same here.

**Every item carries a decisive element matching its label**, drawn from a pair
that shares its topic and vocabulary with the other side. The `sql` pair is
string-formatted SQL against parameterised SQL: same table, same column, same
request body. Only the act differs.

**Difficulty is held fixed**: one cue per item in every slice, drawn
independently of the label. Domain is the variable under test, so nothing else
may move with it. Cues here are texture only. The gradient can point its cues
for or against the label because cue direction is its difficulty knob; doing the
same here would make the cue a second decisive element, and it did — see the
rejected design in README.md.

Two things are deliberately varied:

  domain      code_security, lab_safety, contract_liability
  base rate   0.50 in each domain, plus a 0.25 variant of one of them

The base-rate variant is the control for the finding this experiment is testing.
`analysis/CALIBRATION-TRANSFER.md` reports that Platt's slope stays put across
slices while the intercept moves with the slice's base rate. If that is a real
decomposition rather than a coincidence of the e-mail tiers, then holding the
domain fixed and moving only the base rate should move the intercept and leave
the slope alone.

Known limitation, stated because it bounds what the result can claim: these
items are written by a language model, as the gradient's were. That is the
author bias specified in `analysis/CIRCULARITY.md` §3 and it is not resolved
here. What this experiment controls is the comparison between domains, which
shares the bias and so cannot be explained by it.
"""
from __future__ import annotations

import argparse
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))

# One cue per item, drawn independently of the label, in every slice. Held
# fixed so that domain is the only thing that changes between slices.
CUES_PER_ITEM = 1

SLICES = [
    {"name": "code_security", "domain": "code_security", "base_rate": 0.50},
    {"name": "lab_safety", "domain": "lab_safety", "base_rate": 0.50},
    {"name": "contract_liability", "domain": "contract_liability", "base_rate": 0.50},
    # Same domain as the first slice, different base rate: the intercept control.
    {"name": "code_security_rare", "domain": "code_security", "base_rate": 0.25},
]


def build(spec: dict, index: int, positive: bool, rng: random.Random) -> dict:
    pair = rng.choice(spec["decisive_pairs"])
    decisive = pair["positive" if positive else "negative"]

    # Drawn WITHOUT reference to the label. An earlier version of this generator
    # drew cues from label-specific pools, as lab/tiers/generate.py does, and a
    # regex on the cue vocabulary then scored 100% on every slice: the cue was a
    # second decisive element. The gradient can do that because cue direction is
    # its difficulty knob; here difficulty is held fixed, so a cue that tracks
    # the label is pure leakage. Recorded in README.md.
    cues = rng.sample(spec["cues"], min(CUES_PER_ITEM, len(spec["cues"])))

    preamble = (
        spec["preamble"]
        .replace("{n}", str(1000 + index))
        .replace("{file}", rng.choice(spec["files"]))
        .replace("{proc}", rng.choice(spec["files"]))
        .replace("{person}", rng.choice(spec["people"]))
        .replace("{role}", rng.choice(spec["roles"]))
    )

    lines = [preamble, ""]
    for cue in cues:
        lines.append(cue["text"])
    lines.append(decisive)
    return {
        "text": "\n".join(lines),
        "decisive_topic": pair["topic"],
        "cue_kinds": sorted(c["kind"] for c in cues),
    }


def generate(per_slice: int = 120, seed: int = 20260921) -> list:
    rng = random.Random(seed)
    with open(os.path.join(HERE, "components.json"), encoding="utf-8") as fh:
        parts = json.load(fh)["domains"]

    items = []
    for slice_spec in SLICES:
        spec = parts[slice_spec["domain"]]
        base = slice_spec["base_rate"]
        # Deterministic positions rather than sampling, so the realised base rate
        # is exactly the stated one and does not drift with the seed.
        step = 1.0 / base
        positives = {int(round(k * step)) for k in range(int(per_slice * base))}
        for i in range(per_slice):
            positive = i in positives
            built = build(spec, i, positive, rng)
            items.append(
                {
                    "id": f"{slice_spec['name'][:4]}{i:03d}",
                    "slice": slice_spec["name"],
                    "domain": slice_spec["domain"],
                    "base_rate": base,
                    "label": "positive" if positive else "negative",
                    "is_positive": positive,
                    "decisive": built["decisive_topic"],
                    "cues": built["cue_kinds"],
                    "question": spec["question"],
                    "criteria": {"true": spec["positive"], "false": spec["negative"]},
                    "text": built["text"],
                }
            )
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(HERE, "dataset.jsonl"))
    ap.add_argument("--per-slice", type=int, default=120)
    ap.add_argument("--seed", type=int, default=20260921)
    args = ap.parse_args(argv)

    items = generate(args.per_slice, args.seed)
    with open(args.out, "w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, sort_keys=True) + "\n")
    print(f"Wrote {len(items)} items to {args.out}")
    for spec in SLICES:
        rows = [i for i in items if i["slice"] == spec["name"]]
        pos = sum(1 for i in rows if i["is_positive"])
        print(
            f"  {spec['name']:<20} n={len(rows):<4} positive={pos:<3} "
            f"negative={len(rows) - pos:<3} realised base rate={pos / len(rows):.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
