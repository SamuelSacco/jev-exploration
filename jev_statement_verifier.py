#!/usr/bin/env python3
"""Jev verification layer for a brokerage statement extraction pipeline.

Jev cannot generate text, so it cannot extract fields. The pattern is:

  1. Your existing extractor (an LLM, an OCR pipeline) pulls fields from the PDF.
  2. Jev verifies each extracted field against the statement text (Noul), classifies
     the broker (Choice), and rates completeness (Score) -- in one parallel call.

Usage:
  export TYPESAFE_API_KEY=ts-...
  python3 jev_statement_verifier.py statement.txt fields.json
  python3 jev_statement_verifier.py statement.txt fields.json --noul-band 0.05 0.95
  python3 jev_statement_verifier.py statement.txt fields.json --json > result.json

statement.txt is text extracted from the PDF; fields.json is your extractor's JSON
output. Standard library only.

On thresholds: the defaults below are guesses. This repo's whole argument is that
thresholds have to be fitted on your own labelled data, so treat --noul-band and
--min-confidence as the knobs you are supposed to tune, and see
docs/claims-audit.md section 6 for why confidence may not mean what you want it to.
"""
import argparse
import json
import sys

from jevlab.client import JevClient, JevError, escalations


def build_questions(fields: dict) -> dict:
    """One verification question per extracted field, plus broker and completeness."""
    questions = {}
    for name, value in fields.items():
        label = name.replace("_", " ")
        questions[f"verify_{name}"] = {
            "type": "noul",
            "instructions": (
                f"Does this brokerage account statement indicate that the "
                f"{label} is {value}?"
            ),
        }
    questions["which_broker"] = {
        "type": "choice",
        "instructions": "Which brokerage firm issued this statement?",
        "criteria": {
            "schwab": "Charles Schwab",
            "fidelity": "Fidelity Investments",
            "vanguard": "Vanguard",
            "merrill": "Merrill / Bank of America",
            "other": "A different brokerage or unclear",
        },
    }
    questions["completeness"] = {
        "type": "score",
        "instructions": "How complete is this statement text for extracting account details?",
        "criteria": [
            "Truncated or missing major sections",
            "Mostly complete, some sections missing",
            "Complete statement with all sections present",
        ],
    }
    return questions


def format_report(resp, flagged: list) -> str:
    lines = [
        f"model={resp.model} "
        f"input_tokens={resp.usage.get('input_tokens', '?')} "
        f"elapsed={resp.elapsed_s:.2f}s",
        "",
    ]
    for key, ans in resp.answers.items():
        kind = ans.get("type")
        if kind == "noul":
            lines.append(f"{key}: {ans['noul']:.3f}")
        elif kind == "choice":
            probs = " ".join(f"{k}={v:.2f}" for k, v in ans["probabilities"].items())
            lines.append(
                f"{key}: -> {ans['choice']} (conf {ans['confidence']:.2f}) [{probs}]"
            )
        elif kind == "score":
            lines.append(f"{key}: {ans['score']:.2f} (conf {ans['confidence']:.2f})")
    if flagged:
        lines.append("")
        lines.append("Flagged for human review:")
        for qid, reason, value in flagged:
            lines.append(f"  {qid}: {reason} ({value})")
    return "\n".join(lines)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("statement", help="text extracted from the PDF")
    parser.add_argument("fields", help="your extractor's JSON output")
    parser.add_argument(
        "--noul-band",
        nargs=2,
        type=float,
        metavar=("LOW", "HIGH"),
        default=(0.1, 0.9),
        help="escalate Noul answers falling between these bounds (default 0.1 0.9)",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.6,
        help="escalate Choice/Score answers below this confidence (default 0.6)",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the raw response plus escalations"
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    with open(args.statement, encoding="utf-8") as fh:
        state = fh.read()
    with open(args.fields, encoding="utf-8") as fh:
        fields = json.load(fh)

    try:
        resp = JevClient().ask(state, build_questions(fields))
    except JevError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    flagged = escalations(
        resp,
        noul_band=tuple(args.noul_band),
        min_confidence=args.min_confidence,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "model": resp.model,
                    "elapsed_s": round(resp.elapsed_s, 3),
                    "usage": resp.usage,
                    "answers": resp.answers,
                    "escalations": [
                        {"question": q, "reason": r, "value": v} for q, r, v in flagged
                    ],
                },
                indent=2,
            )
        )
    else:
        print(format_report(resp, flagged))

    # Non-zero exit when anything needs a human, so a pipeline can gate on it.
    return 2 if flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())
