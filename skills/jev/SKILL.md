---
name: "jev"
description: "Call TypeSafe's Jev model (System One judgments: Noul, Choice, Score)."
---

# Jev API

## Purpose
Run Jev evaluations over a state with typed questions; verify extracted statement fields, classify brokers, score completeness in one parallel call.

## Tooling
`bin/jev.py` — minimal CLI, standard library only (urllib), no dependencies.
It reads the key from the environment:

```
export TYPESAFE_API_KEY=<redacted>
python3 bin/jev.py request.json   # POST the JSON payload in request.json
```

Payload shape: `{"state": "...", "model": "jev-latest", "questions": {"q1": {"type": "noul", "instructions": "...", "criteria": {...}}}}`.
Prints the provider's JSON response to stdout.

## Auth
Export `TYPESAFE_API_KEY`. Never commit it, never paste it into shared logs,
never pass it as a command-line flag (it would land in shell history).
A 401 or 403 is a question about the request before it is a question about the
key: check the key was exported, then check it is valid and correctly scoped.

## Operating Rules
1. Use this skill when the user asks for Jev API or this provider's API.
2. Restrict authenticated requests to: api.typesafe.ai.
3. Do not print, log, or persist raw credentials.
4. If auth is missing or rejected, follow the Auth section rather than asking for a key.
