# Structural probes

What the API's request shape does, measured rather than assumed.

```bash
python3 lab/probe_structure.py --dry-run
JEV_TRANSPORT=my_ops.jev:send python3 lab/probe_structure.py --repeat 3
```

Run 2026-09-20 on `jev-1.13.0`, 24 calls. Three probes, each with its
expectation written into `PREDICTIONS` before the run. **All three predictions
held.**

> **Provenance: reported, not reproducible from this repository.** The run was
> executed by the operator who holds the credential, and its raw responses were
> not returned here, so `lab/runs/` carries nothing behind these numbers and
> they cannot be re-binned or re-checked. That breaks the rule in
> `lab/runs/README.md`. `python3 analysis/provenance.py` lists this and the
> other affected claims. The figures stand as reported; what is missing is the
> ability to audit them, and the fix is to commit
> `lab/runs/*-probe-*.jsonl` from that run.

## 1. Questions are isolated from each other's instructions

A code word was planted in one question's `instructions` and a second question
in the same request was asked about it.

| where the code word was | probability on the second question |
|---|---|
| in another question's instructions | 0.02 |
| in the shared state | 0.99 |

Absent-word controls stayed low in both conditions.

So a request is one shared `state` plus questions that cannot see each other.
Batching unrelated judgements into one call does not leak instruction text
between them, which is what makes every batched experiment in this repo valid,
and it is a contract detail TypeSafe's documentation does not state.

## 2. Batching is close to free

| | |
|---|---|
| marginal cost per question | ~0.33 ms |
| fixed overhead per request | ~1.425 s |

A 400-question request costs about 1.6 s; a 1-question request costs about
1.43 s. The overhead is the call, not the work, so batch aggressively: 100
questions in one request beat 100 requests by roughly two orders of magnitude in
wall clock. This is the strongest operational finding in the repo and it costs
nothing to act on.

## 3. Choice concentrates where independent Nouls do not

On a classification item, asked both ways:

| formulation | probability mass on the correct label | mass left on distractors |
|---|---|---|
| one Choice over the labels | all of it | 0.00 |
| one Noul per label, independently | — | 0.29 |

The Nouls do not compete: nothing normalises them against each other, so each is
free to be confident about its own label and 0.29 ends up on answers that are
wrong.

**This is a caveat on most of this repo.** The difficulty gradient, the negation
probe and the cross-domain slices are all built from Nouls, so if the effect
holds at scale, they measure a formulation as well as a model, and the ledger's
calibration findings are about the weaker of the two shapes Jev offers.

It is one item, which is not enough to act on. `lab/exp_headtohead.py` carries a
`typed` arm that asks the 120 hardest gradient items as a two-option Choice
against the same items as Nouls, with a bootstrap interval on the difference, to
find out whether it survives contact with a harder slice.

## Related

`analysis/quantisation.py` covers what resolution the answers come back at, and
finds Choice and Score reaching exactly 0 and 1 where Noul never does. The two
results point the same way: the primitives are not interchangeable, and a result
should name which one produced it.
