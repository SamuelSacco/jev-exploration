# Review of the external claim sweep, 2026-09-18 to 2026-09-20

An outside sweep catalogued 22 official TypeSafe claims (O1–O22), 53 third-party
claims (T1–T53) and 20 of its own findings (S1–S20), each with a verdict and
evidence. This is a review of that document from this repo's position, plus the
code added in response.

```bash
python3 analysis/sweep/audit.py       # audit its calibration figures, no API key
python3 lab/probe_structure.py --dry-run
```

## What it adds

Four things this repo did not have.

**The latency verdict changes.** Ledger row 9 called the 70–500 ms claim
overstated as a user-facing figure, on the basis that measurements here came in at
1.47 s. The sweep collects four independent direct-client measurements inside the
band: openchamber's survey median 76 ms (n=333), anisselbd 239 ms p50 from France,
robipop22 294 ms median, and chetaslua 415 ms median over 1,191 calls. Its own CLI
path also stays above 1.35 s, matching the finding here that a subprocess-per-call
harness measures its own overhead. The band is reachable; the claim is fair as
service time.

**A third independent calibration datapoint.** Verdict-open-jev reports Jev at ECE
0.144 on 2,000 typed decisions, against a TF-IDF logistic regression at ECE 0.0207
with comparable accuracy. That lands beside jev-phishing-bench's 0.154 and supports
the conclusion here that calibration is task-dependent and worse on realistic tasks
than on synthetic verification. The sweep flags, correctly, that the Jev row may be
derived from TypeSafe's published dashboard rather than measured live, so the
provenance is weaker than the number looks.

**A reproducible code-review benchmark.** gemanor/jev-code-review-benchmark: 360
calls per model on a 4-rule Python review, Jev 98% against Gemini Flash and Claude
Fable at 100%, 45× and 274× cheaper, median 0.75 s against 3.59 s and 4.31 s. That
is the first independently published accuracy gap with a method attached.

**Three structural properties worth testing.** Questions inside one request are
isolated from each other's instruction text; 1,000 questions add roughly 0.3 ms
each; and binary-per-item formulations leave far more probability on distractors
than a single Choice does. The last one matters here directly, because both the
difficulty gradient and the negation probe are built from Nouls.

## Where it over-reads its own evidence

The sweep marks O13 ("calibrated: higher confidence means higher accuracy") as
PROVEN where testable, citing ECE 0.054 at n=80 and ECE 0.054 at n=40. It does not
compute a noise floor for either.

`analysis/sweep/audit.py` does, sweeping across three plausible output
distributions because the floor depends on the shape of the output as well as the
sample size:

| claim | n | ECE | ratio to floor | verdict |
|---|---|---|---|---|
| O13-reproducer | 100 | none reported | — | bin monotonicity is not an ECE |
| O13-skeptic | 80 | 0.054 | 0.49× to 2.01× | unresolvable |
| T6-extraction-bound | 40 | 0.054 | 0.36× to 1.39× | at the floor |
| T22-verdict-open-jev | 2,000 | 0.144 | 6.6× to 26.7× | above the floor |
| T15-phishing-bench | 2,000 | 0.154 | 7.0× to 28.6× | above the floor |
| B3-negation | 80 | 0.065 | 0.58× to 2.42× | unresolvable |

Floors, by sample size and output distribution:

```
       n         spread   concentrated        bimodal
      40         0.1497         0.0667         0.0387
      80         0.1111         0.0419         0.0269
     100         0.1004         0.0434         0.0257
    2000         0.0219         0.0121         0.0054
```

So the n=40 figure sits at or below its floor under every reading, and the n=80
figure reads as noise or as a real effect depending on a fact the sweep does not
state. Neither establishes calibration. This is the same error jev-benchmark made
at n=60, which the sweep itself cites this repo for identifying.

Two things follow, and the second is the more useful one.

The sweep's own caveat is sharper than its verdict. It notes that bins 0.1–0.4 were
empty on both domains, so the literal "0.2 → 20%" mapping is untestable from
observed output. A calibration claim tested only at the extremes is exactly the
jev-spam-eval situation documented in [`analysis/external/`](../external/): the
extremes looked excellent there too, while the middle of the curve was off by up to
0.28. Empty mid-bins are a reason the claim cannot be checked, not a caveat on a
claim that has been.

And the fix is cheap. B3 in the table above is this repo's own negation probe, and
it is equally unresolvable from n and ECE alone. Because the raw responses are
committed, the audit resolves it exactly: ECE 0.0649 against a floor of 0.0518, a
ratio of 1.25, at the floor. The simulated range spans noise to real; the raw pairs
collapse it to one answer. Publishing (probability, outcome) pairs costs nothing
and removes the ambiguity entirely.

## Smaller notes

**S3 conflicts with an earlier observation.** The sweep reports that ambiguous
pronoun referents draw a confident False (0.10–0.16) rather than the ~0.5 an
honest-uncertainty story predicts, and flags it for follow-up. The edge probes in
ledger §1 found 0.49 on an unknowable question. Both are small-n, and they may be
probing different things: an unanswerable question against a question with a
well-formed but unresolvable referent. Worth separating before either is cited.

**The Score payload shape does not match what works here.** S12 reports Score
`criteria` as a list of `{question, min, max}` dicts returning a criterion index.
The triage demo in this repo passes a list of level descriptions and gets a
position back, and that has run successfully against the live API. Either the API
accepts both shapes or one of the observations is of a different endpoint version.
Nothing here has been changed on the strength of it.

**Verdict inflation.** PROVEN is used for n=1 observations in places, and for
patterns established on synthetic projections (S1). The document is careful about
evidence elsewhere, which makes the label worth tightening.

## Code added in response

`analysis/sweep/audit.py` audits externally reported calibration figures against
their noise floors, reading `claims.json`. It reports a range across output
distributions rather than a point, and marks a claim unresolvable when the range
spans noise to signal. Where this repo holds the raw pairs, it resolves the claim
exactly instead.

`lab/probe_structure.py` tests the three structural claims, with a prediction
written before the run and checked afterwards:

- **isolation**: a code word placed in one question's instructions against the same
  word in the shared state, with absent-word controls on both. Predicts below 0.30
  in a sibling question and above 0.70 in the state.
- **batching**: wall clock against question count at 1, 25, 100 and 400, fitting a
  marginal cost per question. Predicts under 5 ms.
- **formulation**: one Choice over four classes against four independent Nouls on
  the same item, comparing the probability mass left on wrong classes.

24 calls at the default settings. `--dry-run` sizes the run and prints the
predictions without a key.

The formulation probe is the one that could change existing results here. If a
single Choice suppresses distractors where parallel Nouls do not, then the
800-item difficulty gradient and the 80-item negation probe, both built from Nouls,
measure a formulation as much as a model. That would be worth knowing before the
cross-domain work in #9.
