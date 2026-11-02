"""Expired human sign-ins release machine automation and close native windows."""

import json
import os
from datetime import timedelta

import pytest

from yoke_contracts.timestamps import format_instant, utc_now
from yoke_harness import browser_human_gate as gate
from yoke_harness import desktop_browser_sign_in as desktop
from yoke_harness.browser_sign_in_limits import AUTHORIZATION_LIMIT_MS, SHUTDOWN_MS


@pytest.mark.parametrize(
    "age_ms,active",
    [
        (AUTHORIZATION_LIMIT_MS - 1, True),
        (AUTHORIZATION_LIMIT_MS + SHUTDOWN_MS, True),
        (AUTHORIZATION_LIMIT_MS + SHUTDOWN_MS + 1, False),
    ],
)
def test_gate_bound_applies_even_to_a_live_pid(tmp_path, monkeypatch, age_ms, active):
    now = utc_now()
    monkeypatch.setattr(gate, "utc_now", lambda: now)
    marker = tmp_path / gate.HUMAN_GATE_FILE_NAME
    record = {
        "pid": os.getpid(),
        "identity": "operator",
        "project": "example",
        "started_at": format_instant(now - timedelta(milliseconds=age_ms)),
    }
    marker.write_text(json.dumps(record))
    assert gate.active_human_gate(tmp_path) == (record if active else None)
    assert marker.exists() is active
    if not active:
        gate.refuse_during_human_gate(tmp_path)


@pytest.mark.parametrize("started_at", [None, "invalid"])
def test_invalid_timestamp_cannot_hold_gate_forever(tmp_path, started_at):
    marker = tmp_path / gate.HUMAN_GATE_FILE_NAME
    marker.write_text(json.dumps({"pid": os.getpid(), "started_at": started_at}))
    assert gate.active_human_gate(tmp_path) is None
    assert not marker.exists()


@pytest.mark.parametrize("kind", ["Safari", "Chromium"])
def test_desktop_timeout_quits_browser_before_reporting_failure(monkeypatch, kind):
    calls = []
    times = iter([0, 0, AUTHORIZATION_LIMIT_MS / 1000])
    monkeypatch.setattr(desktop.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(desktop.time, "sleep", lambda _: None)
    monkeypatch.setattr(desktop, "window_count", lambda _: 1)
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **kw: None)
    monkeypatch.setattr(
        desktop, "quit_browser", lambda selected: calls.append(selected)
    )
    with pytest.raises(RuntimeError, match="desktop_browser_sign_in_timeout") as error:
        desktop.sign_in_window(kind, ["https://example.test"])
    assert calls == [kind]
    assert "without resetting" in str(error.value)
