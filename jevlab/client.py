"""A single Jev HTTP client, with the retry behaviour the API reference asks for.

Standard library only. This module is the one place in the repo that talks to
api.typesafe.ai; the CLI, the verifier and the lab harness all go through it.

    from jevlab.client import JevClient

    client = JevClient()                      # key from TYPESAFE_API_KEY
    resp = client.ask("Ticket text...", {
        "urgent": {"type": "noul", "instructions": "Is this urgent?"},
    })
    print(resp.noul("urgent"), resp.elapsed_s)
"""
from __future__ import annotations

import json
import os
import random
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"

# The API reference documents 429 and 529 as back-off conditions. 5xx is included
# because a transient server error is not usefully distinguishable from overload.
RETRY_STATUS = {429, 500, 502, 503, 504, 529}


class JevError(RuntimeError):
    """Any failure talking to the API."""


class JevHTTPError(JevError):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body[:500]}")


@dataclass
class JevResponse:
    """One API response, plus what it cost to obtain."""

    raw: dict
    elapsed_s: float
    attempts: int = 1
    requested_at: str = ""

    @property
    def answers(self) -> dict:
        return self.raw.get("answers", {})

    @property
    def model(self) -> str:
        """The concrete model version that served the call, e.g. jev-1.13.0.

        Worth recording with every result: 'jev-latest' is a moving target.
        """
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

    def confidence(self, qid: str) -> float | None:
        """Confidence for Choice and Score. Noul has no confidence field."""
        return self.answers[qid].get("confidence")

    def probabilities(self, qid: str) -> dict:
        return self.answers[qid].get("probabilities", {})


@dataclass
class JevClient:
    api_key: str | None = None
    url: str = API_URL
    model: str = DEFAULT_MODEL
    timeout: float = 60.0
    max_attempts: int = 5
    base_backoff: float = 1.0
    max_backoff: float = 32.0
    # Injected in tests so the suite never sleeps or opens a socket.
    _opener: Any = None
    _sleep: Any = field(default=time.sleep)

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("TYPESAFE_API_KEY")

    def _require_key(self) -> str:
        if not self.api_key:
            raise JevError(
                "TYPESAFE_API_KEY is not set. Export your TypeSafe API key first."
            )
        return self.api_key

    def ask(
        self,
        state: Any,
        questions: dict,
        model: str | None = None,
    ) -> JevResponse:
        """POST one evaluation and return the parsed response.

        Retries 429/5xx/529 with exponential backoff and jitter, honouring
        Retry-After when the server sends it. 401 and 422 are not retried:
        a bad key or a malformed question will fail the same way every time.
        """
        payload = {
            "state": state,
            "model": model or self.model,
            "questions": questions,
        }
        return self.post(payload)

    def post(self, payload: dict) -> JevResponse:
        """POST a raw payload. Fills in `model` if the caller omitted it."""
        payload = dict(payload)
        payload.setdefault("model", self.model)
        body = json.dumps(payload).encode("utf-8")
        requested_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        last_error: Exception | None = None
        started = time.monotonic()

        for attempt in range(1, self.max_attempts + 1):
            try:
                raw = self._once(body)
            except JevHTTPError as exc:
                last_error = exc
                if exc.status not in RETRY_STATUS or attempt == self.max_attempts:
                    raise
                self._sleep(self._backoff(attempt, getattr(exc, "retry_after", None)))
            except urllib.error.URLError as exc:
                last_error = JevError(f"network error: {exc.reason}")
                if attempt == self.max_attempts:
                    raise last_error from exc
                self._sleep(self._backoff(attempt, None))
            else:
                return JevResponse(
                    raw=raw,
                    elapsed_s=time.monotonic() - started,
                    attempts=attempt,
                    requested_at=requested_at,
                )

        raise last_error or JevError("exhausted retries")

    def _once(self, body: bytes) -> dict:
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._require_key()}",
            },
            method="POST",
        )
        opener = self._opener or urllib.request.urlopen
        try:
            with opener(req, timeout=self.timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            err = JevHTTPError(exc.code, text)
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            err.retry_after = _parse_retry_after(retry_after)
            raise err from None

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_backoff)
        window = min(self.base_backoff * (2 ** (attempt - 1)), self.max_backoff)
        # Full jitter: spreads retries out when several callers back off together.
        return random.uniform(0, window)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # HTTP-date form; fall back to exponential backoff.


def measure_network_floor(
    host: str = "api.typesafe.ai",
    port: int = 443,
    samples: int = 5,
) -> dict:
    """Time TCP connect plus TLS handshake to the API host.

    This is the floor any end-to-end latency figure sits on top of. Reporting
    request latency without it makes the model look slow in proportion to how
    far you are from the service: jev-phishing-bench measured a 163 ms floor
    under a 239 ms p50, so most of what looked like model time was distance.

    Costs nothing and needs no API key.
    """
    ctx = ssl.create_default_context()
    timings = []
    for _ in range(samples):
        started = time.monotonic()
        with socket.create_connection((host, port), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host):
                timings.append(time.monotonic() - started)
    timings.sort()
    return {
        "host": host,
        "samples": samples,
        "min_s": round(timings[0], 4),
        "p50_s": round(timings[len(timings) // 2], 4),
        "max_s": round(timings[-1], 4),
    }


def escalations(
    resp: JevResponse,
    noul_band: tuple = (0.1, 0.9),
    min_confidence: float = 0.6,
) -> list:
    """Questions whose answers are not decisive enough to act on unreviewed.

    Covers all three primitives, which a Noul-only rule does not: a Choice can
    return a winner at 0.52 with confidence 0.04, and nothing about the winner
    alone tells you that happened.

    The defaults here are starting guesses, not recommendations. Fit them on
    your own labelled data; that is the whole argument of this repo.
    """
    low, high = noul_band
    flagged = []
    for qid, ans in resp.answers.items():
        kind = ans.get("type")
        if kind == "noul":
            if low < float(ans["noul"]) < high:
                flagged.append((qid, "noul in uncertain band", ans["noul"]))
        elif kind in ("choice", "score"):
            conf = ans.get("confidence")
            if conf is not None and float(conf) < min_confidence:
                flagged.append((qid, "low confidence", conf))
    return flagged
