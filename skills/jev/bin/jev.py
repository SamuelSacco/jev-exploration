#!/usr/bin/env python3
"""Call TypeSafe's System One evaluation endpoint (Jev).

Usage:
  export TYPESAFE_API_KEY=ts-...   # your key from your TypeSafe account
  python3 jev.py request.json       # POST the JSON payload in request.json
  python3 jev.py < request.json    # or pipe the payload on stdin

Payload shape (per https://docs.typesafe.ai/api.md):
  {"state": "...", "model": "jev-latest",
   "questions": {"q1": {"type": "noul", "instructions": "...", "criteria": {...}}}}

Prints the provider's JSON response to stdout.
"""
import json
import os
import sys
import urllib.request
import urllib.error

API_URL = "https://api.typesafe.ai/v1/systemone"


def main() -> int:
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        print("TYPESAFE_API_KEY is not set. Export your TypeSafe API key first.",
              file=sys.stderr)
        return 1

    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    else:
        payload = json.load(sys.stdin)

    payload.setdefault("model", "jev-latest")

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
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.load(resp)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {body}", file=sys.stderr)
        if exc.code in (429, 529):
            print("Rate limited / overloaded — back off and retry with exponential backoff.",
                  file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
