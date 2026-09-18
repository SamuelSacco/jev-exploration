# Raw run records

One JSONL file per demo per invocation, named `<UTC timestamp>-<demo>.jsonl`, one
line per pass. Each line carries the full unmodified API response plus the model
version, request time, observed round trip and attempt count.

These are committed on purpose. Summary statistics cannot be re-derived, re-binned
or re-checked after the fact, and the earlier version of this lab discarded its raw
responses, which is why none of its published numbers can be audited now.

Written before scoring, so a paid call survives a crash in the analysis code.
