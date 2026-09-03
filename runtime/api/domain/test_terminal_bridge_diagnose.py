"""Each Terminal-bridge capability, diagnosed on its own, with its recovery."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runtime.api.domain.terminal_bridge_host_test_support import (
    BRIDGE_IDENTITY,
    FakeMac,
)
from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_AUTOMATION_UNAVAILABLE_ERROR_CODE,
    TERMINAL_BRIDGE_CHECKS,
    TERMINAL_BRIDGE_RECOVERY,
    TERMINAL_CONSOLE_USER_MISMATCH_ERROR_CODE,
    TERMINAL_DISPLAY_LOCKED_ERROR_CODE,
    TERMINAL_SECURE_KEYBOARD_ENTRY_ON_ERROR_CODE,
    TERMINAL_SYSTEM_EVENTS_UNAVAILABLE_ERROR_CODE,
    TERMINAL_WINDOW_FOCUS_TIMEOUT_ERROR_CODE,
)
from yoke_harness import ssh_mac_terminal_app, ssh_mac_terminal_bridge_check
from yoke_harness.ssh_mac_terminal_bridge_diagnose import (
    diagnose_terminal_app_control,
)


def _diagnose(mac: FakeMac, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        ssh_mac_terminal_bridge_check,
        "uuid4",
        lambda: SimpleNamespace(hex=BRIDGE_IDENTITY.ljust(32, "b")),
    )
    monkeypatch.setattr(
        "yoke_harness.ssh_mac_terminal_bridge_window_probe.uuid4",
        lambda: SimpleNamespace(hex=BRIDGE_IDENTITY.ljust(32, "b")),
    )
    return diagnose_terminal_app_control(mac, expected_console_user="yoke-test")


def _rows(result) -> dict[str, dict]:
    return {row["name"]: row for row in result.evidence["checks"]}


def test_a_healthy_host_reports_every_capability_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _diagnose(FakeMac(), monkeypatch)

    assert result.ok, result.error_code
    assert result.error_code is None
    assert [row["name"] for row in result.evidence["checks"]] == list(
        TERMINAL_BRIDGE_CHECKS
    )
    assert all(row["ok"] for row in result.evidence["checks"])
    assert result.evidence["host"]["console_user"] == "yoke-test"
    assert result.evidence["host"]["display_locked"] is False
    assert result.evidence["first_failed_check"] is None


def test_one_missing_grant_produces_one_failure_and_no_consequences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A capability whose precondition failed is reported as not run, because
    # five red lines for one revoked grant read like five problems.
    result = _diagnose(FakeMac(system_events_reachable=False), monkeypatch)

    assert not result.ok
    assert result.error_code == TERMINAL_SYSTEM_EVENTS_UNAVAILABLE_ERROR_CODE
    rows = _rows(result)
    assert rows["ssh_transport"]["ok"] is True
    assert rows["console_session"]["ok"] is True
    failing = rows["system_events_control"]
    assert (
        failing["recovery"]
        == (TERMINAL_BRIDGE_RECOVERY[TERMINAL_SYSTEM_EVENTS_UNAVAILABLE_ERROR_CODE])
    )
    assert "-1743" in failing["observed"]["detail"]
    for name in TERMINAL_BRIDGE_CHECKS[3:]:
        assert rows[name]["outcome"] == "not_run"
        assert rows[name]["blocked_by"] == "system_events_control"
    assert result.evidence["first_failed_check"] == "system_events_control"


def test_terminal_automation_is_diagnosed_separately_from_system_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _diagnose(FakeMac(terminal_app_reachable=False), monkeypatch)

    assert result.error_code == TERMINAL_AUTOMATION_UNAVAILABLE_ERROR_CODE
    rows = _rows(result)
    assert rows["system_events_control"]["ok"] is True
    assert "Automation for Terminal" in rows["terminal_app_control"]["recovery"]


def test_secure_keyboard_entry_is_named_before_any_key_is_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # macOS discards synthetic keystrokes silently while it is on, so a run
    # that typed anyway would report a transcript timeout instead.
    result = _diagnose(FakeMac(secure_keyboard_entry=True), monkeypatch)

    assert result.error_code == TERMINAL_SECURE_KEYBOARD_ENTRY_ON_ERROR_CODE
    rows = _rows(result)
    assert rows["secure_keyboard_entry"]["observed"]["secure_keyboard_entry"] is True
    assert rows["window_launch"]["outcome"] == "not_run"
    assert result.evidence["host"]["secure_keyboard_entry"] is True


def test_a_console_owned_by_another_login_is_named_before_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _diagnose(FakeMac(console_user="root"), monkeypatch)

    assert result.error_code == TERMINAL_CONSOLE_USER_MISMATCH_ERROR_CODE
    rows = _rows(result)
    assert rows["console_session"]["observed"]["console_user"] == "root"
    assert rows["display_frame"]["outcome"] == "not_run"


def test_a_locked_screen_is_named_before_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _diagnose(FakeMac(locked=True), monkeypatch)

    assert result.error_code == TERMINAL_DISPLAY_LOCKED_ERROR_CODE
    assert _rows(result)["console_session"]["observed"]["display_locked"] is True


def test_a_window_that_never_becomes_frontmost_names_what_held_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mac = FakeMac(frontmost_process="Finder", load_average=0.0)
    clock = {"now": 0.0}

    def advance(seconds: float) -> None:
        clock["now"] += seconds

    monkeypatch.setattr(
        ssh_mac_terminal_app.time,
        "monotonic",
        lambda: clock["now"],
    )
    monkeypatch.setattr(ssh_mac_terminal_app.time, "sleep", advance)

    result = _diagnose(mac, monkeypatch)

    assert result.error_code == TERMINAL_WINDOW_FOCUS_TIMEOUT_ERROR_CODE
    focus = _rows(result)["window_focus"]
    assert focus["observed"]["frontmost_process"] == "Finder"
    assert focus["observed"]["wait_seconds"] > 0
    assert (
        focus["recovery"]
        == (TERMINAL_BRIDGE_RECOVERY[TERMINAL_WINDOW_FOCUS_TIMEOUT_ERROR_CODE])
    )


def test_the_diagnosis_reports_the_load_that_sized_its_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _diagnose(FakeMac(load_average=3.0), monkeypatch)

    assert result.evidence["host"]["load_average"] == 3.0
    focus = _rows(result)["window_focus"]
    assert focus["observed"]["load_average"] == 3.0
    assert focus["observed"]["wait_seconds"] > 5.0
