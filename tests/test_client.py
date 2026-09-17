"""Client tests. No network, no sleeping, no API key."""
import io
import json
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
