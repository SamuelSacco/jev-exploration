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
import urllib.parse
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


def _no_proxy_matches(host: str) -> bool:
    """True if NO_PROXY exempts this host. '*' exempts everything; '.foo' matches
    any subdomain of foo; a bare name matches itself and its subdomains."""
    # Both spellings are merged rather than one taking precedence: a caller that
    # exempts a host in either place means it, and silently reading only one is
    # the kind of surprise that costs an afternoon.
    raw = ",".join(
        v for v in (os.environ.get("no_proxy"), os.environ.get("NO_PROXY")) if v
    )
    host = host.lower().rstrip(".")
    for entry in (e.strip().lower().rstrip(".") for e in raw.split(",")):
        if not entry:
            continue
        if entry == "*":
            return True
        entry = entry.lstrip(".")
        if host == entry or host.endswith("." + entry):
            return True
    return False


def _proxy_for(scheme: str = "https", host: str | None = None) -> tuple | None:
    """The configured proxy as (host, port), or None if unset or NO_PROXY exempts host."""
    if host and _no_proxy_matches(host):
        return None
    for var in (f"{scheme}_proxy", f"{scheme.upper()}_PROXY", "all_proxy", "ALL_PROXY"):
        value = os.environ.get(var)
        if value:
            parsed = urllib.parse.urlparse(value if "//" in value else f"//{value}")
            if parsed.hostname:
                return (parsed.hostname, parsed.port or (443 if scheme == "https" else 80))
    return None


def _connect_via_proxy(proxy: tuple, host: str, port: int, timeout: float):
    """Open a tunnel through an HTTP proxy with CONNECT. Returns (socket, seconds)."""
    started = time.monotonic()
    sock = socket.create_connection(proxy, timeout=timeout)
    try:
        sock.sendall(
            f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode()
        )
        # Read just the status line and headers, not the tunnelled body.
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise OSError("proxy closed the connection during CONNECT")
            buf += chunk
            if len(buf) > 65536:
                raise OSError("proxy sent an oversized CONNECT response")
        status = buf.split(b"\r\n", 1)[0].decode("latin-1")
        if " 200" not in status:
            raise OSError(f"proxy refused CONNECT: {status}")
    except Exception:
        sock.close()
        raise
    return sock, time.monotonic() - started


def measure_network_floor(
    host: str = "api.typesafe.ai",
    port: int = 443,
    samples: int = 5,
) -> dict:
    """Time the transport setup that every request pays before the model sees it.

    Every end-to-end latency figure sits on top of this floor. Reporting request
    latency without it makes the model look slow in proportion to distance from
    the service: jev-phishing-bench measured a 163 ms floor under a 239 ms p50.

    Behind an HTTP proxy a direct socket fails the TLS handshake (the proxy
    answers with an HTTP response, which reads as WRONG_VERSION_NUMBER), so the
    tunnel is established with CONNECT first. The two phases are reported
    separately because they mean different things: `connect_s` through a proxy
    is environment overhead that a differently deployed caller would not pay,
    while `tls_s` is closer to genuine distance. Subtracting the whole floor
    from a request time therefore gives an *upper* bound on service time.

    Costs nothing and needs no API key.
    """
    proxy = _proxy_for("https", host)
    ctx = ssl.create_default_context()
    totals, connects, handshakes = [], [], []

    for _ in range(samples):
        if proxy:
            sock, connect_s = _connect_via_proxy(proxy, host, port, timeout=10)
        else:
            started = time.monotonic()
            sock = socket.create_connection((host, port), timeout=10)
            connect_s = time.monotonic() - started
        try:
            started = time.monotonic()
            with ctx.wrap_socket(sock, server_hostname=host):
                tls_s = time.monotonic() - started
        finally:
            sock.close()
        connects.append(connect_s)
        handshakes.append(tls_s)
        totals.append(connect_s + tls_s)

    def p50(values: list) -> float:
        return round(sorted(values)[len(values) // 2], 4)

    totals.sort()
    result = {
        "host": host,
        "samples": samples,
        "via_proxy": f"{proxy[0]}:{proxy[1]}" if proxy else None,
        "min_s": round(totals[0], 4),
        "p50_s": p50(totals),
        "max_s": round(totals[-1], 4),
        "connect_p50_s": p50(connects),
        "tls_p50_s": p50(handshakes),
    }
    if proxy:
        result["note"] = (
            "Measured through an HTTP proxy. connect_p50_s is the proxy's CONNECT "
            "setup, which is environment overhead rather than distance to the API. "
            "Treat the implied service time as an upper bound."
        )
    return result


def escalations(
    resp: JevResponse,
    noul_band: tuple = (0.1, 0.9),
    min_confidence: float = 0.6,
) -> list:
    """Questions whose answers are not decisive enough to act on unreviewed.

    Covers all three primitives. A Choice can return a winner at 0.52 with
    confidence 0.04, which the winner alone does not reveal.

    The defaults are starting points rather than recommendations; fit them on
    labelled data from the target domain.
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
