"""A seam for running experiments under someone else's credential handling.

Experiments in this repo normally call `JevClient`, which reads
`TYPESAFE_API_KEY` from the environment. Some operators hold the credential in
their own store and inject it through their own transport. Those experiments
should contain no credential code at all, not even an environment read.

So an experiment calls `resolve_sender()` and gets back:

    send(state, questions, model="jev-latest") -> raw response dict

Default: `jevlab.client.JevClient`, key from the environment.

Override: set `JEV_TRANSPORT` to `package.module:callable`. The callable takes
`(state, questions, model)` and returns the raw response dict. Whatever it does
about authentication is its own business and invisible here.

    JEV_TRANSPORT=my_ops.jev:send python3 lab/exp_circularity.py --repeat 3

A sender may also expose `.elapsed_s` on the returned dict under the key
`_elapsed_s`; experiments use it for latency when present and fall back to timing
the call themselves.
"""
from __future__ import annotations

import importlib
import os
import time

ENV_VAR = "JEV_TRANSPORT"


def _default_sender():
    from jevlab.client import JevClient

    client = JevClient()

    def send(state, questions, model: str = "jev-latest") -> dict:
        resp = client.ask(state, questions, model=model)
        raw = dict(resp.raw)
        raw["_elapsed_s"] = resp.elapsed_s
        raw["_attempts"] = resp.attempts
        return raw

    return send


def resolve_sender():
    """Return the callable this run should send requests through."""
    spec = os.environ.get(ENV_VAR)
    if not spec:
        return _default_sender()
    if ":" not in spec:
        raise ValueError(
            f"{ENV_VAR} must look like 'package.module:callable', got {spec!r}"
        )
    module_name, attr = spec.split(":", 1)
    module = importlib.import_module(module_name)
    sender = getattr(module, attr)
    if not callable(sender):
        raise TypeError(f"{spec} is not callable")
    return sender


def describe_sender() -> str:
    spec = os.environ.get(ENV_VAR)
    return spec if spec else "jevlab.client.JevClient (credential from the environment)"


def timed(sender, state, questions, model: str = "jev-latest") -> tuple:
    """Call the sender and return (raw, elapsed_seconds)."""
    started = time.monotonic()
    raw = sender(state, questions, model)
    elapsed = raw.get("_elapsed_s")
    return raw, (elapsed if elapsed is not None else time.monotonic() - started)
