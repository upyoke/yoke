"""Tests for direct Stop / SessionEnd cleanup."""

from __future__ import annotations

import psycopg
import pytest

from runtime.harness.hook_runner import session_end_cleanup as _sec


class FakeConn:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _clock_seq(values: list[float]):
    iterator = iter(values)

    def _clock() -> float:
        try:
            return next(iterator)
        except StopIteration:
            return values[-1]

    return _clock


@pytest.fixture(autouse=True)
def _capture_failures(monkeypatch: pytest.MonkeyPatch):
    sent = []
    monkeypatch.setattr(
        _sec, "emit_session_hook_failed", lambda **kw: sent.append(kw),
    )
    yield sent


def test_resolve_timeout_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_sec, "get_int", lambda key, default: default)
    assert _sec.resolve_cleanup_timeout_ms() == _sec.CLEANUP_TIMEOUT_DEFAULT_MS


def test_resolve_timeout_reads_config_key(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake_get_int(key, default):
        seen["key"] = key
        seen["default"] = default
        return 4321

    monkeypatch.setattr(_sec, "get_int", fake_get_int)
    assert _sec.resolve_cleanup_timeout_ms() == 4321
    assert seen == {
        "key": _sec.CLEANUP_TIMEOUT_CONFIG_KEY,
        "default": _sec.CLEANUP_TIMEOUT_DEFAULT_MS,
    }


def test_cleanup_success_calls_domain_cleanup_in_process() -> None:
    captured = {}
    conn = FakeConn()

    def fake_connect(timeout_ms):
        captured["timeout_ms"] = timeout_ms
        return conn

    def fake_cleanup(cleanup_conn, session_id):
        captured["conn"] = cleanup_conn
        captured["session_id"] = session_id

    ok = _sec.run_session_end_cleanup(
        "/repo", "sess-ok", executor="codex", event_source="Stop",
        timeout_override_ms=500, _connect=fake_connect, _cleanup=fake_cleanup,
    )

    assert ok is True
    assert captured == {
        "timeout_ms": 500,
        "conn": conn,
        "session_id": "sess-ok",
    }
    assert conn.closed is True


def test_db_connect_error_emits_failure(_capture_failures: list) -> None:
    def fake_connect(timeout_ms):
        raise psycopg.OperationalError("connection failed")

    ok = _sec.run_session_end_cleanup(
        "/repo", "sess-locked", executor="codex", event_source="Stop",
        timeout_override_ms=250, _connect=fake_connect,
    )

    assert ok is False
    assert _capture_failures[-1]["reason"] == "OperationalError"
    assert _capture_failures[-1]["hook_event"] == "Stop"
    assert _capture_failures[-1]["extra"]["timeout_ms"] == 250


def test_cleanup_exception_emits_failure(_capture_failures: list) -> None:
    conn = FakeConn()

    def fake_cleanup(_conn, _session_id):
        raise RuntimeError("boom")

    ok = _sec.run_session_end_cleanup(
        "/repo", "sess-bad", executor="claude-code", event_source="SessionEnd",
        _connect=lambda _timeout_ms: conn, _cleanup=fake_cleanup,
        _clock=_clock_seq([1.0, 1.05]),
    )

    assert ok is False
    assert _capture_failures[-1]["hook_event"] == "SessionEnd"
    assert _capture_failures[-1]["reason"] == "RuntimeError"
    assert _capture_failures[-1]["extra"]["error"] == "boom"
    assert _capture_failures[-1]["latency_ms"] == 50
    assert conn.closed is True
