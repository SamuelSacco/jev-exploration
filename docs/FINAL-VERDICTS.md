# Final verdicts

Every substantive claim this repo makes about Jev, one line each, as of
2026-09-25 (`jev-1.13.0`). Evidence pointers go to the ledger
(`docs/claims-audit.md`), which carries the numbers.

| Claim | Verdict |
|---|---|
| One endpoint, `{state, model, questions}` in, `{model, answers, usage}` out | Verified |
| Questions batch into one call without a latency blowup | Verified |
| Output tokens free; input $0.042/MTok | Verified |
| 255-option Choice cap, ~32k token budget | Verified |
| No published rate limits, SLA, or uptime commitment | Verified (absent) |
| Honest uncertainty on unanswerable questions | Verified, small n |
| "193.6× faster / 444.6× cheaper" | Overstated |
| "Similar intelligence to frontier LLMs" | Overstated |
| 70–500 ms end-to-end | Fair as service time; not reachable on every client path |
| "Can't hallucinate" / 0% structured-output errors | Refuted |
| "New model class" as a scientific category | Unmeasured |
| An ordinary LLM can reproduce the interface | Verified |
| Probabilities are calibrated | Refuted at scale — real miscalibration, both large studies |
| Confidence is safe to route and escalate on | Depends on the sign of the error, not the size of the ECE |
| Calibration holds when the model is out of its depth | Yes as a function; harder inputs land where it is worst |
| Returned probabilities are full-precision floats | Refuted — 0.01 grid across 11,148 answers |
| A returned probability can be exactly 0 or 1, unfixable by rescaling | Verified for Choice and Score; no Noul instance in 11,148 |
| Batched questions cannot see each other's instructions | Verified |
| Batching is near-free (~0.4 ms per extra question) | Verified |
| Choice and independent Nouls measure the same thing | Contested — Nouls left 0.29 on distractors where Choice left none, n=1 |
| Judgements far more repeatable than an LLM judge's | Verified for repeatability, not correctness |
| A benchmark whose labels the model supplied is inflated by ~0.08 | Refuted as a constant — +0.005 here; scales with decidability |
| 50 labels refit the intercept (61.7% held-out ECE reduction) | Verified, and a floor not a plateau; sits at the n=100 noise floor |
| B1 (calibration invariance) more fragile to label error than B2 (p≥0.9 hit rate) | Verified — 1 flip (0.5%) vs 3 flips (1.5%) |
| H1: Jev beats the lexical bar where expected | Refuted — cleared it on adversarial too |
| H2: local 4B wins home_turf, loses negation | Partial — lost both halves on home_turf, won on negation |
| H3: Jev calibrates better on every arm | Partial — 3 of 4; local better on negation |
| H4: typed Choice beats adversarial Noul | Refuted — +2.5 pts, CI covers zero |
| The fitted slope transfers across domains (issue #9 H1) | Partial — 0 of 3 new-domain slopes in the email band |
| The correction decomposes into stable slope + slice intercept (issue #9 H2) | Partial — point estimates clear the thresholds; 95% CIs do not fully |
| The transfer recipe generalises (issue #9 H3) | Holds on the fixed recipe — refit and scoring sets now disjoint |
| Negation probe: slope-only transfer reaches a different task | Holds — 0.070 → 0.020/0.019/0.019/0.021 held-out; headroom was small |

What would change the most minds from here: a second model version (does the
slope survive a retrain), a non-email domain with headroom, and a larger-n
replication of the 61.7% at a block size where the noise floor stops binding.
