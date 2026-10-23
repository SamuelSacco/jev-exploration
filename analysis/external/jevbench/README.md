# Verification: Khosla, "Confident Where People Disagree" (issue #17)

**Original work — not ours.** Gautam Khosla ([GautamTalksDev](https://github.com/GautamTalksDev))
preregistered and ran this study, and posted it here as
[issue #17](../../issues/17) on 2026-09-29, crediting issue #1 as the first
public version of the question.

- Paper: https://doi.org/10.5281/zenodo.22971492
- Code and preregistration: https://github.com/GautamTalksDev/jevbench
- Video walkthrough: https://youtu.be/C6chAhTWvP4

His claim: Jev Choice probabilities, scored against the share of annotators
choosing the model's top label, are far worse calibrated on
high-human-disagreement ChaosNLI items than on low-disagreement items —
bias-corrected ΔECE = **0.2636** (750 easy + 750 hard). Ledger record: **T327**.

**This directory is our independent verification of that claim** (2026-10-21).
Everything below the line is ours; the claim, the item sets, the prompt, and
the estimator are his.

## Result

Reproduces within noise.

| Quantity | His | Ours (pass A) |
|---|---|---|
| ECE easy (raw) | 0.0760 | 0.0727 |
| ECE hard (raw) | 0.3391 | 0.3414 |
| Corrected ΔECE | **0.2636** | **0.2665** |
| Corrected 95% CI | [0.2439, 0.2782] | [0.2448, 0.2790] |

Three independent passes: 0.2665 / 0.2645 / 0.2677 (SD 0.0016). Robust across
estimator variants (0.2622–0.2687). Mechanism, pass A hard stratum: mean
confidence 0.807 vs mean annotator agreement 0.467 (his paper: 0.807 vs 0.468).

Noise floor, computed separately (`scripts/run_noisefloor.py`): under a
perfectly calibrated predictor on his exact strata, his estimator yields
ΔECE 0.0000 deterministically and at most 0.0109 across 1,800 Monte Carlo
replicates. The method cannot manufacture the effect.

## Method

- Item sets verified against `jevbench/preregistration.lock.json` (SHA-256
  match on `items.jsonl` and `labels.jsonl`) and reconstructed with his code:
  identical 750/750 sets, 0 mismatches. Sentence text hydrated from the
  ChaosNLI mirrors his code pins (hashes match). See
  `results/setup_verification.json`.
- Estimator imported from `jevbench`, not reimplemented; his seeds.
- Fresh Jev calls, one per item per pass, 4,538 total (spend:
  `spend_log.jsonl`, `results/spend.json`). The API served the pinned
  `jev-1.13.0` on every call — the version string reads `jev-1.13.0` in all
  4,510 saved responses.

Deviations from his call construction, all logged in the raw records:

1. Choice question only. His call bundled three Noul questions in the same
   request; his own API reference states questions in one call are evaluated
   in isolation, and the endpoint under test uses only the Choice
   probabilities. The Noul arm was not replicated — it is not the claim under
   test (his Noul corrected Δ was 0.076, reported as inconclusive).
2. Transport: his client is the `typesafe_sdk`; `scripts/run_pass.py` calls a
   local CLI that POSTs the same payload to the same native endpoint
   (`api.typesafe.ai/v1/systemone`). Payload and endpoint unchanged.

## Contents

- `scripts/` — `setup_items.py` (item-set verification and hydration),
  `run_pass.py` (one pass of 1,500 calls), `analyze.py` (his estimator over a
  pass), `run_noisefloor.py` (calibrated-null distribution of the estimator).
- `raw/pass{A,B,C}.jsonl`, `raw/passsmoke.jsonl` — per-item request payload +
  raw response, one JSON object per line, exactly as saved at call time.
- `data/items_full.jsonl` — the 1,500 hydrated items as called.
- `results/analysis.json` — primary and robustness numbers for all passes;
  `results/setup_verification.json` — hash and reconstruction checks;
  `results/noisefloor.json` — the null distribution summary.
- `spend_log.jsonl`, `results/spend.json` — the call budget record.

Scope note: this verifies the differential (hard vs easy strata). It says
nothing about miscalibration shared by both strata, and it does not conflict
with finding B1 in this repo — B1 is Noul, binary ground truth, stratified by
task difficulty on synthetic email; this is Choice, annotator agreement
share, stratified by human disagreement.
