# Jev: an exploratory thread

Everything from a two-day deep dive into [TypeSafe's Jev](https://typesafe.ai) (launched Sept 15, 2026) — a "System One" judgment API that returns typed probabilities instead of generated text. Claim audit, live demos with measured numbers, the full thread, and runnable code.

**TL;DR:** Jev is classifier-shaped and LLM-emulable, but its bet — training for *calibrated* decisions — is the one claim nobody has verified yet. The right posture is using it as a decision layer inside code-owned workflows, and the decisive experiment is a calibration curve on your own data.

---

## The API in 60 seconds

One endpoint. That's the whole surface area:

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

Three primitives, that's the entire expressive surface:

| Primitive | Returns | Shape |
|---|---|---|
| **Noul** | P(yes) as a float | `{"type": "noul", "noul": 0.92}` |
| **Choice** | winner + full probability distribution + confidence | `{"type": "choice", "choice": "technical", "probabilities": {...}, "confidence": 0.82}` |
| **Score** | position along your ordered descriptive levels (can land between them) | `{"type": "score", "score": 1.6, "legend": {...}, "probabilities": {...}, "confidence": 0.78}` |

Key semantics (verified live, model `jev-1.13.0`):

- **Question IDs are yours** and are echoed back — they are *not* sent to the model. The model cannot choose an option you omitted.
- **Noul near 0.5** means yes/no are similarly probable (uncertainty), *not* "medium intensity". Noul has no separate confidence field.
- **Confidence = concentration of the distribution**, not proof of correctness and not permission to act.
- **State = evidence, instructions = the judgment, criteria = the answer space.** You're designing a measurement instrument, not writing a prompt.
- Code owns the workflow: Jev never generates text, never calls your functions, never decides what happens next. Thresholds, routing, escalation — all in your code.
- Errors: `401` bad key, `422` malformed question, `429` / `529` → back off with exponential retries (official SDKs do this by default). No public numeric rate limits, no SLA, no uptime commitment. Limits: 255 Choice options, ~32k input tokens/request.
- Pricing: **$0.042 / million input tokens, output tokens free.**

---

## What I measured (live, 7 API calls)

| Demo | Setup | Result | Cost |
|---|---|---|---|
| **Support triage** | 12 hand-labeled tickets × 3 judgments (department, urgency, frustration), **one call**, 1.61 s | Dept 10/12, urgency 12/12, frustration MAE 0.25. Both "misses" were ambiguous labels (defensible judgments, not errors) | 3,357 in / 997 out tokens ≈ **$0.00014** |
| **RAG rerank** | 8 passages (4 relevant, 4 distractors), one Noul each, **one call**, 1.69 s | 8/8 correct, perfect ranking — relevant 0.94–0.98 vs distractors 0.01 | 975 in / 140 out tokens |
| **Statement verification** | GPT-extracts → Jev-verifies brokerage statement | Clean fields 0.99; planted transposed digit ($1,274,392.11 → $1,284,392.11) → **0.01** with auto-escalation; truncated doc → completeness 0.01 at 0.99 confidence | — |
| **Edge cases** | Unknowable question → **0.49**; contradictory evidence → **0.40**; forced Choice with no valid option → picked at 0.52 with **0.04 confidence** (the distribution flags garbage-in); irrelevant-state question answered from world knowledge (0.04) | The product is the *distribution*, not the answer | — |

Reproduce: `lab/` holds the data (`tickets.json`, `rerank.json`), the runner (`run_demos.py`), and the measured `results.json`. See [Run it yourself](#run-it-yourself).

---

## Claim audit: verified / true-but-smaller / debunked / unproven

Full write-up: [`docs/claims-audit.md`](docs/claims-audit.md). The short version:

**Verified**
- The HTTP contract, parallel batching, tiny free outputs, and honest-uncertainty behaviors above.
- 255-option Choice cap and ~32k-token budget are documented; numeric rate limits, SLA, and uptime commitments are confirmed *absent*.

**True, but smaller than the marketing**
- **Speed/cost multipliers**: official surfaces say 193.6×/444.6×, 40–200×, 20–200×, and 100× — and TypeSafe admits the headlines are "on the higher end of real world gains." Independent tests: ~5× faster / 8.6× cheaper (Near Here, n=50 real moderation decisions), ~25× faster / ~580× cheaper (Every, vs a heavy-reasoning flagship). Direction true; headlines best-case.
- **"Frontier intelligence"**: TypeSafe's own evals show Jev *tying a mid-tier LLM* (67.8% vs 67.9%) and trailing top reasoning models — and the reference answers were averages of two other LLMs, not ground truth. Independent tests: competitive on bounded classification at ~1/75th the cost. Not frontier.
- **Latency**: they claim 70–500 ms end-to-end; I measured 1.6–3.7 s from my machine (network included). Independent testers got 0.35–0.59 s. Plausible near their infra; not reproduced from here.

**Debunked (partly by TypeSafe itself)**
- **"Can't hallucinate"**: false as stated. Their 0% chart carries the footnote *"Our number is not empirical. Schema matching is guaranteed."* Their own docs: *"Typed output guarantees the interface, not truth."* Jev can't emit a malformed answer; it can emit a confident wrong valid value. Constrained decoding gives any LLM the same shape guarantee.
- **"New model class" as science**: no weights, no paper, no parameter count, no architecture details. "System One Model" is a product category name. The RLCD training method is a name plus a stated objective ("epistemically honest probabilities") — nothing more is public.

**Still unproven — the important one**
- **Calibration.** The central claim has *zero* public evidence: no calibration curve, no ECE figure, no paper. My edge probes are suggestive but prove nothing. The community Enron test (93.7% accuracy at ≥95% confidence, n=9,840) is suggestive but reports no coverage data. **This is the experiment that matters and it hasn't been run.**

---

## The four-camp verdict

| Camp | Verdict |
|---|---|
| "Basically a classifier" | Structurally correct (Noul = binary, Choice = multiclass, Score = ordinal regression). It's a classifier with a natural-language API — that's not nothing. |
| "A normal LLM can do this" | True. The open-source crowd is already replicating the shape (constrained decoding + logit reading). What they can't replicate is the calibration — which TypeSafe also hasn't proven. |
| "New model class" | Unproven. One real idea (calibration as the optimization target), zero public evidence. Marketing until a calibration curve exists. |
| "Use it as a decision layer" | The only actionable camp — and the posture TypeSafe's own docs push: *"validate their performance in the target domain."* |

The feed is arguing about taxonomy. The question is calibration.

---

## The thread

[`docs/thread.md`](docs/thread.md) — 24 posts, beginner-friendly: normal LLM APIs → Ollama → prompt-and-parse → function calling → the trust problem → Jev's contract → the three primitives → the four camps → the verdict.

---

## Repo map

```
├── README.md                      # this file
├── docs/
│   ├── thread.md                  # the 24-post exploratory thread
│   └── claims-audit.md            # full claim audit with sources
├── lab/
│   ├── run_demos.py               # triage + rerank demos, scored vs ground truth
│   ├── tickets.json               # 12 hand-labeled support tickets
│   ├── rerank.json                # query + 8 passages (4 relevant, 4 distractors)
│   ├── results.json               # measured results from the 2026-09-16 run
│   └── edge_payload.json          # edge-case probe payload
├── jev_statement_verifier.py      # brokerage-statement verifier prototype
└── skills/
    ├── jev/
    │   ├── SKILL.md               # Jev skill notes
    │   └── bin/jev.py             # minimal Jev CLI (TYPESAFE_API_KEY from env)
    └── typesafe-ai-SKILL.md       # TypeSafe builder skill (patterns, cookbooks)
```

## Run it yourself

```bash
export TYPESAFE_API_KEY=ts-...          # your key, from your TypeSafe account
python3 skills/jev/bin/jev.py lab/edge_payload.json   # single raw call
python3 lab/run_demos.py                # both demos, scored vs ground truth (2 API calls)
```

`jev.py` is stdlib-only (urllib) — no dependencies. `run_demos.py` shells out to it; override with `JEV_CLI=/path/to/other/client`.

## The decisive experiment (not yet run)

A calibration curve on a few hundred domain-specific labeled cases: predicted probability vs. actual hit rate. If 0.9 ≈ 90%, camp 1 earns the name. If not, it's camp 2 with good marketing. The statement-verifier prototype in this repo is already shaped to run it once fed real extractions.

## Key doc quotes

- *"Typed output guarantees the interface, not truth."*
- *"System One models are trained for calibrated decisions; validate their performance in the target domain."*
- The "can't hallucinate" footnote, their own words: *"Our number is not empirical. Schema matching is guaranteed, thus we can confidently add 0% into the plots."*

---

*Explored 2026-09-16/17. All API calls within normal use (7 total); 429s never hit. Discussion was ~48h old at writing — treat third-party numbers as early signals, not settled science.*
