# Jev: an evidence ledger

Tracking what is actually known about [TypeSafe's Jev](https://typesafe.ai), the "System
One" judgment API that returns typed probabilities instead of generated text. Started as a
two-day deep dive during launch week (Sept 2026); now maintained as a ledger of claims and
the evidence for them, including other people's benchmarks.

**Where the argument stands.** Jev is classifier-shaped and its interface is reproducible
with open models, so the mechanism is not the interesting part. Its bet is that the
probabilities are *calibrated*, and that is now measured rather than merely asserted — but
by fewer studies than it first appears. ECE is badly biased at small n: a perfectly
calibrated model scores about 0.06 at n=60, which is exactly the range one widely cited
benchmark reports, so that result cannot distinguish good calibration from bad. Of the
studies large enough to measure it, one finds Jev well calibrated (spam, n=18.5k, 98.3%
accurate) and one finds it materially miscalibrated and worse than a cheap LLM (phishing,
n=2k, 62.6% accurate). Whether calibration holds when Jev is out of its depth, or only
where it is already accurate, is the open question and the experiment worth running.

→ **[The ledger](docs/claims-audit.md)** — every claim, its status, and the evidence.

---

## The API in 60 seconds

One endpoint. That is the whole surface area:

```http
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer <API key>
Content-Type: application/json
```

```json
{
  "state": "Text, an object, or an array containing the relevant context",
  "model": "jev-latest",
  "questions": {
    "my_question_id": {
      "type": "noul | choice | score",
      "instructions": "The judgment to make",
      "criteria": {}
    }
  }
}
```

Three primitives:

| Primitive | Returns | Shape |
|---|---|---|
| Noul | P(yes) as a float | `{"type": "noul", "noul": 0.92}` |
| Choice | winner + distribution + confidence | `{"type": "choice", "choice": "technical", "probabilities": {...}, "confidence": 0.82}` |
| Score | position along ordered levels, may land between them | `{"type": "score", "score": 1.6, "legend": {...}, "probabilities": {...}, "confidence": 0.78}` |

Semantics worth knowing, verified on `jev-1.13.0`:

- Question IDs are yours and are echoed back. They are not sent to the model, and the model
  cannot pick an option you did not offer.
- Noul near 0.5 means yes and no are similarly probable, not "medium intensity". Noul has
  no separate confidence field.
- Confidence is how concentrated the distribution is. It is not a correctness estimate and
  not permission to act.
- State is the evidence, instructions are the judgment, criteria are the answer space. You
  are designing a measurement instrument, not writing a prompt.
- Code owns the workflow. Jev never generates text, calls your functions, or decides what
  happens next. Thresholds, routing and escalation live in your code.
- Errors: 401 bad key, 422 malformed question, 429/529 back off with exponential retries.
  Limits: 255 Choice options, ~32k input tokens. No published rate limits, SLA or uptime
  commitment.
- Pricing: $0.042 per million input tokens, output tokens free.

## What is in here

```
docs/
  claims-audit.md          the ledger: every claim, status, evidence
  review-and-roadmap.md    audit of this repo's own methodology, and the plan
  thread.md                the original 24-post narrative (frozen snapshot)
jevlab/
  client.py                the one HTTP client: retries, network floor, escalation
  stats.py                 ECE, reliability, Brier, Wilson/bootstrap, ECE noise floor
lab/
  baselines.py             non-AI baselines + Wilson intervals, no API key needed
  run_demos.py             triage + rerank demos, scored against ground truth
  runs/                    raw per-call JSONL, committed so numbers stay auditable
  tickets.json             12 hand-labeled support tickets
  rerank.json              query + 8 passages
  edge_payload.json        edge-case probe payload
  results-2026-09-16-legacy.json   the original run, kept as a non-reproducible record
skills/
  jev/                     minimal Jev CLI + skill notes
  typesafe-ai-SKILL.md     TypeSafe builder skill
jev_statement_verifier.py  extract-then-verify prototype
```

## Run it yourself

No API key needed:

```bash
python3 lab/baselines.py     # non-AI baselines on the bundled datasets
```

With a key:

```bash
export TYPESAFE_API_KEY=ts-...
python3 skills/jev/bin/jev.py lab/edge_payload.json   # single raw call
python3 lab/run_demos.py                              # both demos, one pass each
python3 lab/run_demos.py --repeat 3                   # three passes, variance reported
python3 lab/run_demos.py --dry-run                    # payloads only, no calls
python3 skills/jev/bin/jev.py --floor                 # network floor, no key needed
```

Everything is standard library only. Raw responses land in `lab/runs/*.jsonl` and the
summary in `lab/results.json`; the JSONL is committed, the summary is derived.

## A caveat about our own demos

The triage and rerank demos in `lab/` are n=12 and n=8. Every result they produce has a
95% interval that overlaps a trivial non-AI baseline on the same data, which
`lab/baselines.py` demonstrates. They show what the API shape is good for. They are not
evidence about accuracy, and the ledger does not cite them as such. See
[review-and-roadmap.md](docs/review-and-roadmap.md) for the full methodology critique and
what it would take to fix them.

## Contributing

The ledger is the point: if you have measured something, open a PR adding a row with a
citation. Open issues cover the work in flight, including the calibration-versus-difficulty
experiment.

## Other work worth reading

[jev-benchmark](https://github.com/themsquared/jev-benchmark) ·
[jev-phishing-bench](https://github.com/anisselbd/jev-phishing-bench) ·
[jev-spam-eval](https://github.com/bitnovus/jev-spam-eval) ·
[jev-rerank-bench](https://github.com/anessbelbati/jev-rerank-bench) ·
[openjev](https://github.com/TheoLeeCJ/openjev) ·
[awesome-typesafe](https://github.com/Hawxy/awesome-typesafe)
