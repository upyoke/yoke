"""The shared plan-limit HTTP wrapper keeps a vendor failure's real category.

Claude and Cursor's usage probes, and Codex's HTTP usage-mirror fallback,
all read a vendor failure through this one function. Audited alongside the
codex app-server RPC-error fix (field-note 46471): unlike the app-server
client this wrapper never had a collapsing bug, but it is the shared surface
the fix's diagnostic rule applies to, so it keeps focused regression
coverage of its own — a real HTTP status or exception class must never read
as "unsupported", and must never be swallowed.
"""

from __future__ import annotations

import json
from io import BytesIO
import urllib.error
import urllib.request

from yoke_harness.session_relay_plan_limit_http import plan_limit_http_json


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://example.invalid/usage",
        code=status,
        msg=f"HTTP {status}",
        hdrs=None,  # type: ignore[arg-type]
        fp=BytesIO(b""),
    )


def _install_urlopen(monkeypatch, effect) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: effect())


def test_a_successful_call_returns_the_decoded_document(monkeypatch) -> None:
    _install_urlopen(monkeypatch, lambda: _FakeResponse(json.dumps({"ok": 1}).encode()))
    assert plan_limit_http_json("https://x", headers={}) == {"ok": 1}


def test_a_401_is_named_a_stale_credential(monkeypatch) -> None:
    def _raise():
        raise _http_error(401)

    _install_urlopen(monkeypatch, _raise)
    assert plan_limit_http_json("https://x", headers={}) == "stale_credential"


def test_another_http_status_keeps_its_own_code_instead_of_unsupported(
    monkeypatch,
) -> None:
    def _raise():
        raise _http_error(503)

    _install_urlopen(monkeypatch, _raise)
    assert plan_limit_http_json("https://x", headers={}) == "http_503"


def test_a_transport_failure_keeps_the_exception_class_that_raised(
    monkeypatch,
) -> None:
    def _raise():
        raise TimeoutError("timed out")

    _install_urlopen(monkeypatch, _raise)
    assert (
        plan_limit_http_json("https://x", headers={}) == "http_read_failed_TimeoutError"
    )


def test_a_non_object_body_is_named_rather_than_returned(monkeypatch) -> None:
    _install_urlopen(monkeypatch, lambda: _FakeResponse(json.dumps([1, 2]).encode()))
    assert plan_limit_http_json("https://x", headers={}) == "http_body_not_an_object"
