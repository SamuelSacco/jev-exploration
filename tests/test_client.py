"""Client tests. No network, no sleeping, no API key."""
import io
import json
import os
import urllib.error

import pytest

from jevlab.client import JevClient, JevError, JevHTTPError, JevResponse, escalations


class FakeHTTPResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def ok_body(**answers):
    return {
        "model": "jev-1.13.0",
        "answers": answers,
        "usage": {"input_tokens": 100, "output_tokens": 10},
    }


def opener_returning(*bodies):
    """An opener that yields each body (or raises each error) in turn."""
    calls = {"n": 0}

    def opener(req, timeout=None):
        item = bodies[min(calls["n"], len(bodies) - 1)]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        return FakeHTTPResponse(json.dumps(item).encode())

    opener.calls = calls
    return opener


def http_error(status, retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError(
        "https://api.typesafe.ai/v1/systemone", status, "err", headers, io.BytesIO(b"{}")
    )


def client(opener, **kw):
    kw.setdefault("api_key", "ts-test")
    return JevClient(_opener=opener, _sleep=lambda _s: None, **kw)


def test_missing_key_is_an_error_not_a_crash(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(JevError, match="TYPESAFE_API_KEY"):
        JevClient(_opener=opener_returning(ok_body())).ask("state", {})


def test_model_defaults_are_filled_in():
    opener = opener_returning(ok_body())
    resp = client(opener).ask("state", {"q": {"type": "noul", "instructions": "?"}})
    assert resp.model == "jev-1.13.0"
    assert resp.attempts == 1
    assert resp.elapsed_s >= 0


def test_retries_429_then_succeeds():
    opener = opener_returning(http_error(429), http_error(529), ok_body())
    resp = client(opener).ask("state", {})
    assert resp.attempts == 3
    assert opener.calls["n"] == 3


def test_does_not_retry_401():
    opener = opener_returning(http_error(401), ok_body())
    with pytest.raises(JevHTTPError) as exc:
        client(opener).ask("state", {})
    assert exc.value.status == 401
    assert opener.calls["n"] == 1, "a bad key fails the same way every time"


def test_does_not_retry_422():
    opener = opener_returning(http_error(422), ok_body())
    with pytest.raises(JevHTTPError):
        client(opener).ask("state", {})
    assert opener.calls["n"] == 1


def test_gives_up_after_max_attempts():
    opener = opener_returning(http_error(503))
    with pytest.raises(JevHTTPError):
        client(opener, max_attempts=3).ask("state", {})
    assert opener.calls["n"] == 3


def test_retry_after_header_is_honoured():
    slept = []
    c = JevClient(
        api_key="ts-test",
        _opener=opener_returning(http_error(429, retry_after="7"), ok_body()),
        _sleep=slept.append,
    )
    c.ask("state", {})
    assert slept == [7.0]


def test_retry_after_http_date_falls_back_to_backoff():
    slept = []
    c = JevClient(
        api_key="ts-test",
        _opener=opener_returning(
            http_error(429, retry_after="Wed, 17 Sep 2026 12:00:00 GMT"), ok_body()
        ),
        _sleep=slept.append,
    )
    c.ask("state", {})
    assert len(slept) == 1 and 0 <= slept[0] <= 1.0


def test_accessors():
    resp = JevResponse(
        raw=ok_body(
            a={"type": "noul", "noul": 0.93},
            b={"type": "choice", "choice": "x", "confidence": 0.8, "probabilities": {"x": 0.8}},
            c={"type": "score", "score": 1.6, "confidence": 0.7},
        ),
        elapsed_s=1.0,
    )
    assert resp.noul("a") == 0.93
    assert resp.choice("b") == "x"
    assert resp.score("c") == 1.6
    assert resp.confidence("a") is None, "Noul has no confidence field"
    assert resp.probabilities("b") == {"x": 0.8}


def test_escalations_cover_all_three_primitives():
    """The old rule only looked at Noul, so a 0.52/0.04 Choice passed silently."""
    resp = JevResponse(
        raw=ok_body(
            decisive={"type": "noul", "noul": 0.99},
            unsure={"type": "noul", "noul": 0.55},
            forced={"type": "choice", "choice": "mars", "confidence": 0.04, "probabilities": {}},
            graded={"type": "score", "score": 1.2, "confidence": 0.95},
        ),
        elapsed_s=1.0,
    )
    flagged = {qid for qid, _, _ in escalations(resp)}
    assert flagged == {"unsure", "forced"}


def test_escalation_bands_are_configurable():
    resp = JevResponse(
        raw=ok_body(edge={"type": "noul", "noul": 0.93}), elapsed_s=1.0
    )
    assert escalations(resp) == []
    assert len(escalations(resp, noul_band=(0.05, 0.95))) == 1


# ------------------------------------------------------------------------ proxy


def _clear_proxy_env(monkeypatch):
    """Both spellings of every proxy variable. A CI runner or a sandbox may set
    either, and a test that clears only one silently reads the environment's."""
    for name in ("https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY",
                 "no_proxy", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "no_proxy,host,exempt",
    [
        ("typesafe.ai", "api.typesafe.ai", True),   # bare name covers subdomains
        (".typesafe.ai", "api.typesafe.ai", True),  # leading dot form
        ("typesafe.ai", "typesafe.ai", True),       # and the name itself
        ("*", "anything.example", True),
        ("typesafe.ai", "nottypesafe.ai", False),   # suffix, not subdomain
        ("other.example", "api.typesafe.ai", False),
        ("", "api.typesafe.ai", False),
    ],
)
def test_no_proxy_matching(monkeypatch, no_proxy, host, exempt):
    from jevlab.client import _no_proxy_matches

    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("no_proxy", no_proxy)
    assert _no_proxy_matches(host) is exempt


def test_both_no_proxy_spellings_are_honoured(monkeypatch):
    """Reading only the lowercase form silently ignores an exemption set in the other."""
    from jevlab.client import _no_proxy_matches

    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("no_proxy", "somewhere.else")
    monkeypatch.setenv("NO_PROXY", "typesafe.ai")
    assert _no_proxy_matches("api.typesafe.ai") is True


def test_proxy_is_read_from_the_environment(monkeypatch):
    from jevlab.client import _proxy_for

    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("https_proxy", "http://gateway.internal:8080")
    assert _proxy_for("https", "api.typesafe.ai") == ("gateway.internal", 8080)


def test_uppercase_proxy_is_read_when_lowercase_is_unset(monkeypatch):
    from jevlab.client import _proxy_for

    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://gateway.internal:8080")
    assert _proxy_for("https", "api.typesafe.ai") == ("gateway.internal", 8080)


def test_lowercase_proxy_takes_precedence(monkeypatch):
    """Conventional precedence, and the reason two earlier hand-tests misread."""
    from jevlab.client import _proxy_for

    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("https_proxy", "http://lower.internal:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://upper.internal:2")
    assert _proxy_for("https", "api.typesafe.ai") == ("lower.internal", 1)


def test_proxy_defaults_to_443_without_an_explicit_port(monkeypatch):
    from jevlab.client import _proxy_for

    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("https_proxy", "gateway.internal")
    assert _proxy_for("https", "api.typesafe.ai") == ("gateway.internal", 443)


def test_no_proxy_wins_over_a_configured_proxy(monkeypatch):
    from jevlab.client import _proxy_for

    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("https_proxy", "http://gateway.internal:8080")
    monkeypatch.setenv("no_proxy", "typesafe.ai")
    assert _proxy_for("https", "api.typesafe.ai") is None


def test_connect_tunnel_parses_a_success_response(monkeypatch):
    """The bug this fixes: a direct socket behind a proxy fails the TLS handshake
    with WRONG_VERSION_NUMBER, because the proxy answers in HTTP."""
    from jevlab import client as mod

    sent = []

    class FakeSocket:
        def sendall(self, data):
            sent.append(data)

        def recv(self, _n):
            return b"HTTP/1.1 200 Connection established\r\n\r\n"

        def close(self):
            pass

    monkeypatch.setattr(mod.socket, "create_connection", lambda *a, **k: FakeSocket())
    sock, elapsed = mod._connect_via_proxy(("p", 1), "api.typesafe.ai", 443, 5)
    assert b"CONNECT api.typesafe.ai:443" in sent[0]
    assert elapsed >= 0
    sock.close()


def test_connect_tunnel_raises_on_refusal(monkeypatch):
    from jevlab import client as mod

    class Refusing:
        def sendall(self, data):
            pass

        def recv(self, _n):
            return b"HTTP/1.1 403 Forbidden\r\n\r\n"

        def close(self):
            pass

    monkeypatch.setattr(mod.socket, "create_connection", lambda *a, **k: Refusing())
    with pytest.raises(OSError, match="403"):
        mod._connect_via_proxy(("p", 1), "api.typesafe.ai", 443, 5)


def test_connect_tunnel_raises_when_the_proxy_hangs_up(monkeypatch):
    from jevlab import client as mod

    class Dropping:
        def sendall(self, data):
            pass

        def recv(self, _n):
            return b""

        def close(self):
            pass

    monkeypatch.setattr(mod.socket, "create_connection", lambda *a, **k: Dropping())
    with pytest.raises(OSError, match="closed the connection"):
        mod._connect_via_proxy(("p", 1), "api.typesafe.ai", 443, 5)


# ----------------------------------------------------------------- user agent


def test_every_request_carries_a_stable_user_agent():
    """urllib's default reads as a bot: the skill CLI was Cloudflare-1010'd
    without one on 2026-09-22."""
    from jevlab.client import USER_AGENT

    seen = {}

    def opener(req, timeout=None):
        seen.update(req.headers)
        return FakeHTTPResponse(json.dumps({"model": "m", "answers": {}, "usage": {}}).encode())

    client = JevClient(api_key="k", _opener=opener, _sleep=lambda s: None)
    client.ask("state", {"q": {"type": "noul", "instructions": "i", "criteria": {}}})
    # urllib title-cases header names.
    assert seen.get("User-agent") == USER_AGENT
    assert "jevlab/" in USER_AGENT
    assert "github.com" in USER_AGENT


def test_the_user_agent_is_overridable_per_client():
    seen = {}

    def opener(req, timeout=None):
        seen.update(req.headers)
        return FakeHTTPResponse(json.dumps({"model": "m", "answers": {}, "usage": {}}).encode())

    client = JevClient(
        api_key="k", user_agent="ops/1.0", _opener=opener, _sleep=lambda s: None
    )
    client.ask("state", {"q": {"type": "noul", "instructions": "i", "criteria": {}}})
    assert seen.get("User-agent") == "ops/1.0"


def test_the_user_agent_version_matches_the_package():
    """Two places hold the version; this fails when they drift."""
    import re

    from jevlab.client import USER_AGENT

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as fh:
        declared = re.search(r'^version = "([^"]+)"', fh.read(), re.M).group(1)
    assert f"jevlab/{declared}" in USER_AGENT


def test_the_user_agent_names_no_credential():
    from jevlab.client import USER_AGENT

    for token in ("Bearer", "key", "token", "secret"):
        assert token.lower() not in USER_AGENT.lower()
