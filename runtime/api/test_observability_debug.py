"""Scoped, auto-expiring debug capture on existing structured logs."""

from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta, timezone

import pytest
from yoke_core.api import observability
from yoke_core.api.observability_debug import (
    DEBUG_MAX_RECORDS_ENV,
    DEBUG_SCOPE_ENV,
    DEBUG_UNTIL_ENV,
    DebugCaptureFilter,
    debug_detail_allowed,
    debug_records_emitted,
    parse_debug_campaign,
    reset_debug_state,
)
from yoke_core.api.observability_metrics import metric_attributes


def _until(*, hours: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


@pytest.fixture(autouse=True)
def _reset_campaign_counter() -> None:
    reset_debug_state()
    yield
    reset_debug_state()


def test_campaign_requires_scope_and_until() -> None:
    assert parse_debug_campaign({}) is None
    assert parse_debug_campaign({DEBUG_SCOPE_ENV: "function:items.get.run"}) is None
    assert parse_debug_campaign({DEBUG_UNTIL_ENV: _until()}) is None


def test_expired_until_is_inactive() -> None:
    env = {
        DEBUG_SCOPE_ENV: "function:items.get.run",
        DEBUG_UNTIL_ENV: "2000-01-01T00:00:00Z",
    }
    assert parse_debug_campaign(env) is None
    assert debug_detail_allowed({"function": "items.get.run"}, env=env) is False


def test_matching_function_consumes_budget() -> None:
    env = {
        DEBUG_SCOPE_ENV: "function:items.get.run",
        DEBUG_UNTIL_ENV: _until(),
        DEBUG_MAX_RECORDS_ENV: "2",
    }
    assert debug_detail_allowed({"function": "items.get.run"}, env=env) is True
    assert debug_detail_allowed({"function": "items.get.run"}, env=env) is True
    assert debug_detail_allowed({"function": "items.get.run"}, env=env) is False
    assert debug_records_emitted() == 2


def test_scope_mismatch_does_not_consume() -> None:
    env = {
        DEBUG_SCOPE_ENV: "session:sess-1",
        DEBUG_UNTIL_ENV: _until(),
    }
    assert debug_detail_allowed({"session_id": "other"}, env=env) is False
    assert debug_detail_allowed({"function": "items.get.run"}, env=env) is False
    assert debug_records_emitted() == 0


def test_request_and_service_scopes() -> None:
    until = _until()
    assert debug_detail_allowed(
        {"request_id": "req-9"},
        env={DEBUG_SCOPE_ENV: "request:req-9", DEBUG_UNTIL_ENV: until},
    )
    assert debug_detail_allowed(
        {"service": "yoke-api"},
        env={DEBUG_SCOPE_ENV: "service:yoke-api", DEBUG_UNTIL_ENV: until},
    )


def test_filter_drops_debug_when_campaign_expired() -> None:
    filt = DebugCaptureFilter(logging.INFO)
    record = logging.LogRecord(
        name="yoke.api.dispatch",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=1,
        msg="dispatch.debug",
        args=(),
        exc_info=None,
    )
    record.function = "items.get.run"
    with pytest.MonkeyPatch.context() as patched:
        patched.setenv(DEBUG_SCOPE_ENV, "function:items.get.run")
        patched.setenv(DEBUG_UNTIL_ENV, "2000-01-01T00:00:00Z")
        assert filt.filter(record) is False


def test_filter_allows_matching_debug_and_all_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEBUG_SCOPE_ENV, "function:items.get.run")
    monkeypatch.setenv(DEBUG_UNTIL_ENV, _until())
    filt = DebugCaptureFilter(logging.INFO)
    debug = logging.LogRecord(
        name="yoke.api.dispatch",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=1,
        msg="dispatch.debug",
        args=(),
        exc_info=None,
    )
    debug.function = "items.get.run"
    other = logging.LogRecord(
        name="yoke.api.dispatch",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=2,
        msg="dispatch.debug",
        args=(),
        exc_info=None,
    )
    other.function = "items.list.run"
    info = logging.LogRecord(
        name="yoke.api",
        level=logging.INFO,
        pathname=__file__,
        lineno=3,
        msg="ok",
        args=(),
        exc_info=None,
    )
    assert filt.filter(debug) is True
    assert filt.filter(other) is False
    assert filt.filter(info) is True


def test_process_debug_without_campaign_still_emits() -> None:
    filt = DebugCaptureFilter(logging.DEBUG)
    record = logging.LogRecord(
        name="yoke.api",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=1,
        msg="local",
        args=(),
        exc_info=None,
    )
    assert filt.filter(record) is True


def test_handler_filter_consumes_budget_once_per_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEBUG_SCOPE_ENV, "function:items.get.run")
    monkeypatch.setenv(DEBUG_UNTIL_ENV, _until())
    monkeypatch.setenv(DEBUG_MAX_RECORDS_ENV, "1")
    filt = DebugCaptureFilter(logging.INFO)
    record = logging.LogRecord(
        name="yoke.api.dispatch",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=1,
        msg="dispatch.debug",
        args=(),
        exc_info=None,
    )
    record.function = "items.get.run"
    assert filt.filter(record) is True
    assert filt.filter(record) is True
    assert debug_records_emitted() == 1


def _configure_child_capture(
    monkeypatch: pytest.MonkeyPatch,
    stream: io.StringIO,
    *,
    scope: str,
    until: str,
    max_records: str | None = None,
) -> logging.Logger:
    monkeypatch.setenv(DEBUG_SCOPE_ENV, scope)
    monkeypatch.setenv(DEBUG_UNTIL_ENV, until)
    if max_records is not None:
        monkeypatch.setenv(DEBUG_MAX_RECORDS_ENV, max_records)
    root = logging.getLogger()
    api = logging.getLogger("yoke.api")
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(root, "filters", [])
    monkeypatch.setattr(root, "level", root.level)
    monkeypatch.setattr(api, "level", api.level)
    observability.configure_structured_logging(level="INFO", stream=stream)
    return logging.getLogger("yoke.api.dispatch")


def test_configured_child_logger_mismatch_keeps_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    child = _configure_child_capture(
        monkeypatch, stream, scope="function:items.get.run", until=_until(),
    )
    child.debug("dispatch.debug", extra={"function": "items.list.run"})
    child.info("still-info", extra={"function": "items.list.run"})
    logging.getLogger("unrelated.library").debug("library-debug")
    text = stream.getvalue()
    assert "dispatch.debug" not in text
    assert "library-debug" not in text
    assert "still-info" in text


def test_configured_child_logger_cap_keeps_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    child = _configure_child_capture(
        monkeypatch,
        stream,
        scope="function:items.get.run",
        until=_until(),
        max_records="1",
    )
    extra = {"function": "items.get.run"}
    child.debug("first-debug", extra=extra)
    child.debug("second-debug", extra=extra)
    child.info("still-info", extra=extra)
    text = stream.getvalue()
    assert "first-debug" in text
    assert "second-debug" not in text
    assert "still-info" in text


def test_configured_child_logger_expiry_keeps_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    clock = {"now": live}

    class _FrozenDateTime:
        @staticmethod
        def now(tz=None):
            current = clock["now"]
            if tz is not None:
                return current.astimezone(tz)
            return current

    monkeypatch.setattr("yoke_core.api.observability_debug.datetime", _FrozenDateTime)
    stream = io.StringIO()
    child = _configure_child_capture(
        monkeypatch,
        stream,
        scope="function:items.get.run",
        until=(live + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    extra = {"function": "items.get.run"}
    child.debug("live-debug", extra=extra)
    child.info("live-info", extra=extra)
    live_text = stream.getvalue()
    assert "live-debug" in live_text
    assert "live-info" in live_text

    clock["now"] = live + timedelta(hours=2)
    child.debug("expired-debug", extra=extra)
    child.info("still-info", extra=extra)
    text = stream.getvalue()
    assert "expired-debug" not in text
    assert "still-info" in text
    assert "live-debug" in text


def test_debug_does_not_put_request_id_on_metrics() -> None:
    cleaned = metric_attributes(
        {
            "yoke.function": "items.get.run",
            "yoke.request_id": "req-debug",
            "session_id": "sess-debug",
        }
    )
    assert cleaned == {"yoke.function": "items.get.run"}
