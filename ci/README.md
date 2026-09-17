# CI

`github-workflow.yml` is the CI definition. It is parked here rather than in
`.github/workflows/` because the token that wrote it has no `workflow` scope and
GitHub refuses such a push. To enable it:

```bash
mkdir -p .github/workflows
git mv ci/github-workflow.yml .github/workflows/ci.yml
git commit -m "Enable CI"
```

It runs `pytest`, `lab/baselines.py` and `lab/run_demos.py --dry-run` on Python
3.10 through 3.13. No secret is configured and none is needed: nothing in the
suite touches the network.
