# Footguns: seven traps this repo walked into

Each trap below bit during the analysis this repo documents. Each entry names the
trap, where it bit, and the rule that prevents it. If you only read one file
before contributing, read `docs/claims-audit.md` first; this file is the
appendix that says what went wrong along the way.

## 1. Tie-break non-neutrality

**The trap.** When an adversarial search ties, a deterministic tie-break (lowest
index wins) is reproducible but not neutral. At the first step of the greedy
search in `corrupt_adversarially`, twenty different flips raised ECE by exactly
the same amount, and nineteen did at the second. The "the" greedy answer does
not exist — the tie-break is an arbitrary choice that changes the outcome.

**Where it bit.** `analysis/circularity.py::corrupt_adversarially` (docstring,
~line 110): lowest-index is "deterministic, reproducible, and NOT neutral — on
this data it is consistently the *kindest* choice available to the adversary, so
it overstates how much corruption the finding survives." The deterministic rule
needed 10, 2 and 11 flips across the three passes against the 3, 1 and 3 an
adversary sampling the ties can actually reach (`analysis/CIRCULARITY.md`).

**The rule.** Make tie-breaks a parameter, and headline the value most favorable
to the claim's opponent. `sensitivity_b1` sweeps 20 random tie-breaks plus the
deterministic one and headlines the *minimum* flips to break — because the
adversary chooses.

## 2. Interpreter float differences

**The trap.** The same committed code produced 7, 11 and 12 flips to break B1 on
three machines. Candidate ECEs that tie differ in the last bit or two between
Python 3.11 and 3.12, so an unrounded `>` picked a different flip on each
interpreter.

**Where it bit.** `analysis/circularity.py`, comment above `TIE_PRECISION = 10`
(line ~107): "That is how the same committed code produced 7, 11 and 12 on
three machines." The fix was one constant; every candidate ECE is rounded before
comparison (`round(ece(flip(current, i), bins), TIE_PRECISION)`).

**The rule.** Round to a named precision before comparing floats, and name the
precision at the point of use. In tests, use `pytest.approx` — never `==` on
floats.

## 3. Exact 0/1 breaks every correction

**The trap.** Choice and Score return exact 0/1 freely
(`tests/test_quantisation.py::test_choice_and_score_reach_the_endpoints`). That
is not a rounding artifact; it is unrepairable by rescaling, since logit(0) is
−∞. Meanwhile `jevlab/calibration.py::_clip` (EPS=1e-6) silently corrects a
*different* value — clamping means the fitter never sees the endpoints the API
actually emits, a quiet discrepancy between what was measured and what was fit.

**Where it bit.** The quantisation study (`analysis/quantisation.py`) and its
test gate. Noul is the exception that makes the trap matter: Noul never
returned an endpoint in 2,580+ committed answers, and
`test_noul_never_reached_an_endpoint` fails if a future run ever returns one —
the whole per-primitive calibration caveat rests on that observation
(`docs/claims-audit.md`, the endpoint table). Related correction, same study:
the "residual always absorbed" story was wrong — one jev-1.13.0 choice vector
(rs038: 0.01 + 0.81 + 0.17 + 0.0) sums to 0.99, so
`test_quantised_distributions_almost_sum_to_one` permits {0.99, 1.0} and demands
the audit prose be rewritten, not relaxed, if a second sub-1.0 vector appears.

**The rule.** Exact endpoints and near-1.0 sums are audit failures, not rounding
details. Pin them with a failing test before trusting any correction built on
the data.

## 4. ECE ships with its noise floor or it does not ship

**The trap.** An ECE number alone says nothing. The negation probe scored 80/80
correct with ECE 0.065 — but the floor for n=80 with that distribution is 0.0518
(floor table, `analysis/sweep/README.md`), a ratio of 1.25: unresolvable. The
sample cannot speak to calibration on its own; only the committed raw
(probability, outcome) pairs resolved it exactly.

**Where it bit.** `analysis/sweep/README.md` B3 row ("80 | 0.065 | 0.58× to
2.42× | unresolvable") and `analysis/sweep/claims.json` (`B3-negation`:
"Negation probe, 80/80 correct, ECE 0.065 ~ noise floor"). Same file's audit
notes that jev-benchmark at n=60 reports ECE 0.0505/0.0712 against floors of
0.0452/0.0456 — ratios 1.1–1.6, cannot measure calibration in either direction.

**The rule.** Every ECE ships with its floor ratio; below ~2× it is noise.
Ratio is detectability, not severity: a large n lowers the floor, so it says
whether a study can speak, not how bad the miscalibration is. Publish the raw
pairs — they cost nothing and remove the ambiguity entirely.

## 5. Adversarial ≠ random corruption

**The trap.** Conflating the two inflates robustness. B1's adversarial budget is
1 flip (0.5% of a tier); B2's random-corruption budget is 3 flips (1.5%). B1 is
*more* fragile than B2 — the numbers look similar only if you forget the
adversary sees the answers (`analysis/CIRCULARITY.md` verdict).

**Where it bit.** The same file corrected the headline twice. Two riders came
free with it: the 0.5% is an **upper bound, not the minimum** — greedy search
over sampled tie-breaks can miss a cheaper attack, never invent one, so the
real adversarial budget is at most what is reported and may be smaller. And
`t1_trivial`'s mass leaks into B1's gaps, so the "no bias" verdict is carried by
provenance, not asserted (`analysis/CIRCULARITY.md` lines ~52–54, ~118–140).

**The rule.** Label which corruption regime a robustness number comes from, and
an adversarial number is an upper bound on fragility, never a lower bound on
safety.

## 6. Synthetic-item bias

**The trap.** The tiers are 800 items generated from a 20-pair template pool
(`lab/tiers/FINDINGS.md` caveats). Findings on synthetic items inherit the
template's shape: the decisive-act regex control scores 69.5–83.0% with no
understanding at all, so Jev's 90–98% beats it by less than the raw accuracy
suggests.

**Where it bit.** `lab/tiers/FINDINGS.md` caveats, plus the correction history.
What transferred to jev-spam-eval's 19,528 real emails was the *shape* —
compression toward the middle, the crossover near 0.6 — not the specifics: the
slope band 2.11–2.61 and the 1.000 hit rate at p≥0.9 are tier measurements.
Author bias (the same hand wrote the templates and judged the results) is
flagged UNVERIFIABLE offline: nothing in the repo can rule it in or out.

**The rule.** Shape can transfer; constants don't. Report template-pool
findings with the pool size in the same breath, and mark authorship effects as
unverifiable rather than waving them away.

## 7. Train-on-test

**The trap.** The published recipe — slope transfers, refit the intercept on ~50
labels — reported mean ECE down 74%. The refit set was `test[:50]` and the map
was scored on all 200 items: a quarter of the evaluation set was the data the
intercept was fitted on. Scored on held-out items only, the same budget gives
61.7%, not 74% (`analysis/CALIBRATION-TRANSFER.md`).

**Where it bit.** The repo now keeps `held_out_*` and `contaminated_*` side by
side in `analysis/calibration_set_size.py` so the size of the bias is visible
rather than argued about. That same file's docstring documents a second,
self-inflicted small-n bias: an earlier version evaluated on whatever the refit
did not consume, so the eval set shrank as the budget grew and the curve turned
back up at 150 labels purely from being measured on 50 items — the small-n bias
the repo corrects in published benchmarks, reproduced inside its own analysis.

**The rule.** Score only on items the fit never saw; keep the contaminated
number beside it as the visible size of the bias. Fix the eval set size
independent of the fit budget, or the curve is a mirage.

## Before you publish a number

- [ ] Every ECE has its floor ratio; below ~2× it is noise, not a finding.
- [ ] Corruption numbers name their regime (adversarial vs random); adversarial
      is an upper bound on fragility.
- [ ] Tie-breaks are a parameter; the headline favors the claim's opponent.
- [ ] Floats are compared at a named precision; tests use `pytest.approx`.
- [ ] Endpoint audit: Choice/Score hit exact 0/1; confirm your correction sees
      them too. Distribution sums are {0.99, 1.0}, not guaranteed 1.0.
- [ ] Noul endpoint caveat: still zero in 2,580+? Run the quantisation test.
- [ ] The eval set is disjoint from everything fitted, at a fixed size.
- [ ] Synthetic results cite the template pool; shape claims carry the
      transfer evidence, constant claims stay local.
- [ ] Raw (probability, outcome) pairs are committed behind the number —
      `provenance.py --strict` is green.
