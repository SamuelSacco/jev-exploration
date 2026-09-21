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

`ask()` wraps the call and returns a `Reply`, which is a read-only view over the
raw dict with the same accessors `JevClient` returns. An experiment written
against `Reply` runs unchanged under either transport, which is the point: the
same harness file executes here and on the operator's side.
"""
from __future__ import annotations

import importlib
import os
import time
from dataclasses import dataclass, field

ENV_VAR = "JEV_TRANSPORT"
LOCAL_ENV_VAR = "JEV_LOCAL_TRANSPORT"


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


@dataclass
class Reply:
    """A response, however it was obtained.

    Same accessor surface as `jevlab.client.JevResponse`, so a harness written
    against this runs unchanged whether the calls went through this repo's
    client or an operator's own transport. Deliberately thin: it reads the raw
    dict and holds no connection, credential or retry state.
    """

    raw: dict
    elapsed_s: float = 0.0
    attempts: int = 1
    requested_at: str = ""

    @property
    def answers(self) -> dict:
        return self.raw.get("answers", {})

    @property
    def model(self) -> str:
        """The concrete version that served the call. 'jev-latest' moves."""
        return self.raw.get("model", "")

    @property
    def usage(self) -> dict:
        return self.raw.get("usage", {})

    def noul(self, qid: str) -> float:
        return float(self.answers[qid]["noul"])

    def choice(self, qid: str) -> str:
        return self.answers[qid]["choice"]

    def score(self, qid: str) -> float:
        return float(self.answers[qid]["score"])

    def confidence(self, qid: str):
        """Confidence for Choice and Score. Noul has no confidence field."""
        return self.answers[qid].get("confidence")

    def probabilities(self, qid: str) -> dict:
        return self.answers[qid].get("probabilities", {})

    def legend(self, qid: str) -> dict:
        """Score's level legend, keyed by level index as a string."""
        return self.answers[qid].get("legend", {})


def ask(sender, state, questions, model: str = "jev-latest") -> Reply:
    """Send one request through `sender` and return a `Reply`.

    Keys beginning with an underscore are transport bookkeeping, not part of the
    API response, so they are stripped from `.raw` before anything records it.
    """
    requested_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    raw, elapsed = timed(sender, state, questions, model)
    body = {k: v for k, v in raw.items() if not k.startswith("_")}
    return Reply(
        raw=body,
        elapsed_s=elapsed,
        attempts=int(raw.get("_attempts", 1)),
        requested_at=requested_at,
    )


# --------------------------------------------------------------- local models


def resolve_local_sender():
    """Return the callable a head-to-head run should send local prompts through.

    There is no default. This repo's only approved endpoint is Jev's, so it
    contains no code that can reach an Ollama server, an inference endpoint or
    anything else; the operator supplies that and the seam keeps it outside.

    Set `JEV_LOCAL_TRANSPORT` to `package.module:callable`. The callable takes a
    single prompt string and returns the model's reply as text:

        send(prompt: str) -> str

    Text rather than a parsed probability on purpose. Parsing belongs in this
    repo, where it is versioned and tested, not in the operator's script where
    a quiet change to it would silently move a published number.
    """
    spec = os.environ.get(LOCAL_ENV_VAR)
    if not spec:
        raise RuntimeError(
            f"{LOCAL_ENV_VAR} is not set. This repo holds no local-model "
            "transport of its own: point it at 'package.module:callable' "
            "taking a prompt string and returning the reply text."
        )
    if ":" not in spec:
        raise ValueError(
            f"{LOCAL_ENV_VAR} must look like 'package.module:callable', got {spec!r}"
        )
    module_name, attr = spec.split(":", 1)
    sender = getattr(importlib.import_module(module_name), attr)
    if not callable(sender):
        raise TypeError(f"{spec} is not callable")
    return sender


def describe_local_sender() -> str:
    return os.environ.get(LOCAL_ENV_VAR) or "(unset)"
