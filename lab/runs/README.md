# Raw run records

One JSONL file per demo per invocation, named `<UTC timestamp>-<demo>.jsonl`, one
line per pass. Each line carries the full unmodified API response plus the model
version, request time, observed round trip and attempt count.

These are committed on purpose. Summary statistics cannot be re-derived, re-binned
or re-checked after the fact, and the earlier version of this lab discarded its raw
responses, which is why none of its published numbers can be audited now.

Written before scoring, so a paid call survives a crash in the analysis code.

## Enforcement

The rule above was stated here and not checked, so it broke quietly: an audit of
main on 2026-09-24 found four published runs with no raw responses behind them.

`python3 analysis/provenance.py` lists every CLAIMS entry, the raw files
that back it, and which are missing. `--strict` exits non-zero while any
listed published claim is unbacked, and `tests/test_provenance.py` fails if
a runner matching the covered globs has no entry. The gate is only as
complete as the globs and the CLAIMS list: a figure published by a script
outside `lab/run_*.py`, `lab/exp_*.py`, `lab/probe_*.py`,
`lab/control_*.py`, `lab/repro_*.py`, `lab/score_*.py`, or `lab/laya/*.py`
would not be caught — keep the globs current when adding runners elsewhere.

A claim that cannot be recomputed from this directory is marked
*(raw data not in repo)* in the ledger rather than left looking like the others.

## Scope limit

The seven 2026-09-16 API-contract calls (`docs/claims-audit.md` §1, ledger
rows 1/2/3/6) predate this rule: their raw responses were discarded before the
rule existed, and `analysis/provenance.py` does not guard them — its CLAIMS
cover only the fixture-era runs from 2026-09-18 onward. They are marked honestly
in the ledger (raw responses discarded 2026-09-16; not recomputable) instead of
being silently grandfathered.
