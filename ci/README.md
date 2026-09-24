# CI

The workflow now lives at `.github/workflows/ci.yml` and runs on every push and
pull request.

It runs `pytest`, the dataset controls, every experiment's `--dry-run`, the
offline analyses and the provenance audit, on Python 3.10 through 3.13. No
secret is configured and none is needed: nothing in the suite touches the
network, and every experiment sizes itself without a credential.

`analysis/provenance.py` runs without `--strict` because four runs on main
predate the rule being enforced and have no committed raw responses. Once those
land, switch that step to `--strict` so an unbacked published figure fails CI.

This directory previously held the workflow unparked, because the token that
wrote it had no `workflow` scope and GitHub refuses such a push.
