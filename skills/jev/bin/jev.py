#!/usr/bin/env python3
"""Call TypeSafe's System One evaluation endpoint (Jev).

Usage:
  export TYPESAFE_API_KEY=ts-...          # your key from your TypeSafe account
  python3 jev.py request.json             # POST the JSON payload in request.json
  python3 jev.py < request.json           # or pipe the payload on stdin
  python3 jev.py --floor                  # measure the network floor, no key needed

Payload shape (per https://docs.typesafe.ai/api.md):
  {"state": "...", "model": "jev-latest",
   "questions": {"q1": {"type": "noul", "instructions": "...", "criteria": {...}}}}

Prints the provider's JSON response to stdout, with the observed round trip and
attempt count on stderr so a retried call is visible.

Transport, including 429/529 backoff, lives in the repo's `jevlab` package.
"""
import json
import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

from jevlab.client import JevClient, JevError, measure_network_floor  # noqa: E402


def main() -> int:
    args = sys.argv[1:]

    if "--floor" in args:
        print(json.dumps(measure_network_floor(), indent=2))
        return 0

    try:
        if args:
            with open(args[0], "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        else:
            payload = json.load(sys.stdin)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read payload: {exc}", file=sys.stderr)
        return 1

    try:
        resp = JevClient().post(payload)
    except JevError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        f"[{resp.model or 'unknown model'}] {resp.elapsed_s:.2f}s, "
        f"{resp.attempts} attempt(s)",
        file=sys.stderr,
    )
    print(json.dumps(resp.raw, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
