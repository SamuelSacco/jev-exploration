#!/usr/bin/env python3
"""Jev verification layer for a brokerage statement extraction pipeline.

Jev cannot generate text, so it CANNOT extract fields. The pattern here:
  1. Your existing extractor (e.g. GPT-5.4 on Azure OpenAI) pulls fields from the PDF.
  2. Jev verifies each extracted field against the statement text (Noul = 0..1),
     classifies the broker (Choice), and rates text completeness (Score) --
     in ONE parallel call, ~70-500ms, input tokens only ($0.042/MTok).

Usage:
  export TYPESAFE_API_KEY=<redacted>
  python jev_statement_verifier.py statement.txt fields.json

statement.txt is text extracted from the PDF; fields.json is your extractor's
JSON output (e.g. from GPT-5.4). Standard library only, no dependencies.
"""
import json
import os
import sys
import urllib.request
import urllib.error

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

# What your GPT-5.4 extractor produced -- in real use, pass this in from your pipeline.
EXTRACTED_FIELDS = {
    "account_number": "123-45678",
    "statement_period": "August 1-31, 2026",
    "total_account_value": "$1,284,392.11",
    "broker_name": "Charles Schwab",
}


def build_questions(fields: dict) -> dict:
    questions = {}
    # One yes/no-verification question per extracted field, evaluated in parallel.
    for name, value in fields.items():
        label = name.replace("_", " ")
        questions[f"verify_{name}"] = {
            "type": "noul",
            "instructions": f"Does this brokerage account statement indicate that the {label} is {value}?",
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


def call_jev(state: str, questions: dict) -> dict:
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        sys.exit("TYPESAFE_API_KEY is not set. Export your TypeSafe API key first.")
    payload = {"state": state, "model": MODEL, "questions": questions}
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        sys.exit(f"Jev call failed: HTTP {exc.code}: {body}")


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("Usage: python jev_statement_verifier.py statement.txt fields.json")
    with open(sys.argv[1]) as f:
        state = f.read()  # text extracted from the PDF by your existing pipeline
    with open(sys.argv[2]) as f:
        fields = json.load(f)  # your extractor's JSON output (e.g. from GPT-5.4)

    result = call_jev(state, build_questions(fields))
    answers = result["answers"]
    print(f"model={result['model']} input_tokens={result['usage']['input_tokens']}\n")
    for key, ans in answers.items():
        if ans["type"] == "noul":
            print(f"{key}: {ans['noul']:.3f}")
        elif ans["type"] == "choice":
            probs = " ".join(f"{k}={v:.2f}" for k, v in ans["probabilities"].items())
            print(f"{key}: -> {ans['choice']} (conf {ans['confidence']:.2f}) [{probs}]")
        elif ans["type"] == "score":
            print(f"{key}: {ans['score']:.2f} (conf {ans['confidence']:.2f})")
    # Simple escalation rule: flag any field Jev isn't confident about.
    weak = [k for k, a in answers.items()
            if a["type"] == "noul" and a["noul"] < 0.9]
    if weak:
        print("\nFlagged for human review:", ", ".join(weak))


if __name__ == "__main__":
    main()
