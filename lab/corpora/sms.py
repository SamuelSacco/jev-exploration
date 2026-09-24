"""Import the SMS Spam Collection into this repo's item shape.

    python3 lab/corpora/sms.py --src ~/SMSSpamCollection --out lab/corpora/sms.jsonl
    python3 lab/corpora/sms.py --self-test

Downloads nothing. Point --src at a copy you already have: the UCI file is
tab-separated, `ham` or `spam` then the message, one per line, latin-1 encoded
in the original distribution.

Two importer decisions worth stating, because both change downstream numbers:

**Duplicates are kept and flagged, not dropped.** The collection contains exact
repeats. Dropping them changes n and the base rate, so a figure computed on a
deduplicated copy is not comparable to one computed on the raw file, and the
reported 5,574 is the raw count. `--dedupe` exists and is off by default; the
output records `duplicate_of` either way.

**The encoding is declared.** The original file is latin-1 and reading it as
UTF-8 raises on a handful of messages. Silently replacing those bytes changes
the text of real items, so the encoding is a flag with a latin-1 default rather
than a guess.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "sms_sample.tsv")

LABELS = {"ham": False, "spam": True}


def load(src: str, encoding: str = "latin-1", dedupe: bool = False) -> list:
    rows, seen = [], {}
    with open(src, encoding=encoding) as fh:
        for index, line in enumerate(fh):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            label, _, text = line.partition("\t")
            label = label.strip().lower()
            if label not in LABELS:
                raise ValueError(
                    f"line {index + 1}: label {label!r} is not ham or spam; "
                    "the file format may have moved"
                )
            digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
            first = seen.get(digest)
            if first is not None and dedupe:
                continue
            seen.setdefault(digest, f"sms{index:05d}")
            rows.append(
                {
                    "id": f"sms{index:05d}",
                    "source": "SMSSpamCollection",
                    "label": label,
                    "is_spam": LABELS[label],
                    "text": text,
                    "duplicate_of": first,
                }
            )
    return rows


def summarise(rows: list) -> dict:
    spam = sum(1 for r in rows if r["is_spam"])
    duplicates = sum(1 for r in rows if r["duplicate_of"])
    return {
        "n": len(rows),
        "spam": spam,
        "ham": len(rows) - spam,
        "base_rate": round(spam / len(rows), 4) if rows else 0.0,
        "duplicates": duplicates,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", help="the SMSSpamCollection file")
    ap.add_argument("--out", default=os.path.join(HERE, "sms.jsonl"))
    ap.add_argument("--encoding", default="latin-1")
    ap.add_argument("--dedupe", action="store_true",
                    help="drop exact repeats; changes n and the base rate")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    src = FIXTURE if args.self_test else args.src
    if not src:
        print("Pass --src, or --self-test to run against the bundled fixture.",
              file=sys.stderr)
        return 2

    rows = load(src, args.encoding, args.dedupe)
    summary = summarise(rows)
    print(f"{summary['n']} messages from {src}")
    print(f"  spam {summary['spam']}  ham {summary['ham']}  "
          f"base rate {summary['base_rate']:.1%}  duplicates {summary['duplicates']}")
    if summary["n"] and summary["n"] != 5574 and not args.self_test:
        print(
            f"  note: the reported figures are on 5,574 messages, this copy has "
            f"{summary['n']}. Any comparison has to account for that.",
            file=sys.stderr,
        )

    if args.self_test:
        return 0

    with open(args.out, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
