# CI

`github-workflow.yml` is the CI definition. It is parked here rather than at
`.github/workflows/ci.yml` because neither credential available to this repo's
automation carries GitHub's `workflow` scope: a `git push` is rejected with
"refusing to allow an OAuth App to create or update workflow ... without
`workflow` scope", and the GitHub App route returns `Insufficient scope:
required "repo workflow"`. Both were tried on 2026-09-24.

Enabling it takes one command from an account that has that scope:

```bash
mkdir -p .github/workflows
git mv ci/github-workflow.yml .github/workflows/ci.yml
git commit -m "Enable CI"
```

Nothing else needs to change. No secret is configured and none is needed:
nothing in the suite touches the network, and every experiment sizes itself
without a credential.

## What it runs

On Python 3.10 through 3.13:

- `pytest` — the whole offline suite
- `lab/baselines.py`, `lab/tiers/baselines.py`, `lab/domains/baselines.py` —
  the dataset controls, which exit non-zero if a manipulation stops holding
- every experiment's `--dry-run`, so the credential-free sizing path stays
  credential-free
- `analysis/circularity.py`, `analysis/quantisation.py`,
  `analysis/calibration_transfer.py` — the offline analyses still reproduce
- `analysis/provenance.py` — the raw-data audit

The provenance step runs with `--strict` since 2026-09-24, when the missing raw
runs landed: an unbacked published figure is now a build failure.

Every step above was run locally and exits zero as of 2026-09-24.
