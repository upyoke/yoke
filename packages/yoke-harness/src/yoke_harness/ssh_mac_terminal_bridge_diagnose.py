"""Exercise each Terminal-bridge capability alone and name what blocks it.

Verification answers one question -- can the bridge do its job -- and stops at
the first failure with the condition it could see from there. That is the right
answer for a gate and the wrong one for a person standing in front of a machine
that will not cooperate: they need to know which capability broke, in an order
where each answer is only meaningful once the one before it worked, and what to
change on the host.

So this runs the same capabilities one at a time, host control surfaces first
and the driven window second, and reports every verdict together.
"""

from __future__ import annotations

from yoke_contracts.machine_qa_execution import BRIDGE_DIAGNOSE_OPERATION
from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_AUTOMATION_UNAVAILABLE_ERROR_CODE,
    TERMINAL_BRIDGE_CHECKS,
    TERMINAL_CONSOLE_USER_MISMATCH_ERROR_CODE,
    TERMINAL_DISPLAY_LOCKED_ERROR_CODE,
    TERMINAL_SECURE_KEYBOARD_ENTRY_ON_ERROR_CODE,
    TERMINAL_SSH_UNAVAILABLE_ERROR_CODE,
    TERMINAL_SYSTEM_EVENTS_UNAVAILABLE_ERROR_CODE,
)
from yoke_harness.ssh_mac_display_frame import RunRemote
from yoke_harness.ssh_mac_host_session_state import (
    read_console_user,
    read_display_locked,
    read_load_average,
    read_secure_keyboard_entry,
    system_events_reachable,
    terminal_app_reachable,
)
from yoke_harness.ssh_mac_terminal_bridge_report import BridgeDiagnosisReport
from yoke_harness.ssh_mac_terminal_bridge_window_probe import probe_driven_window
from yoke_harness.test_machine_types import HostActionResult


TRANSPORT_CHECK = TERMINAL_BRIDGE_CHECKS[0]
CONSOLE_SESSION_CHECK = TERMINAL_BRIDGE_CHECKS[1]
SYSTEM_EVENTS_CHECK = TERMINAL_BRIDGE_CHECKS[2]
TERMINAL_CONTROL_CHECK = TERMINAL_BRIDGE_CHECKS[3]
SECURE_KEYBOARD_ENTRY_CHECK = TERMINAL_BRIDGE_CHECKS[4]


def _probe_control_surfaces(
    report: BridgeDiagnosisReport,
    run: RunRemote,
) -> bool:
    """Prove the host is reachable, awake, owned by us, and controllable."""
    transport = run("/usr/bin/true", timeout=20)
    if not report.record(
        TRANSPORT_CHECK,
        ok=transport.returncode == 0,
        observed={"exit_code": transport.returncode},
        error_code=TERMINAL_SSH_UNAVAILABLE_ERROR_CODE,
    ):
        return False

    console_user = read_console_user(run)
    display_locked = read_display_locked(run)
    report.host = {
        "console_user": console_user,
        "expected_console_user": report.expected_console_user,
        "display_locked": display_locked,
        "load_average": read_load_average(run),
    }
    session_ok = bool(console_user) and (
        report.expected_console_user is None
        or console_user == report.expected_console_user
    )
    if not report.record(
        CONSOLE_SESSION_CHECK,
        ok=session_ok and display_locked is False,
        observed={"console_user": console_user, "display_locked": display_locked},
        error_code=(
            TERMINAL_CONSOLE_USER_MISMATCH_ERROR_CODE
            if not session_ok
            else TERMINAL_DISPLAY_LOCKED_ERROR_CODE
        ),
    ):
        return False

    events_ok, events_detail = system_events_reachable(run)
    if not report.record(
        SYSTEM_EVENTS_CHECK,
        ok=events_ok,
        observed={"detail": events_detail},
        error_code=TERMINAL_SYSTEM_EVENTS_UNAVAILABLE_ERROR_CODE,
    ):
        return False

    terminal_ok, terminal_detail = terminal_app_reachable(run)
    if not report.record(
        TERMINAL_CONTROL_CHECK,
        ok=terminal_ok,
        observed={"detail": terminal_detail},
        error_code=TERMINAL_AUTOMATION_UNAVAILABLE_ERROR_CODE,
    ):
        return False

    secure_entry = read_secure_keyboard_entry(run)
    report.host["secure_keyboard_entry"] = secure_entry
    return report.record(
        SECURE_KEYBOARD_ENTRY_CHECK,
        ok=not secure_entry,
        observed={"secure_keyboard_entry": secure_entry},
        error_code=TERMINAL_SECURE_KEYBOARD_ENTRY_ON_ERROR_CODE,
    )


def diagnose_terminal_app_control(
    run: RunRemote,
    *,
    expected_console_user: str | None = None,
) -> HostActionResult:
    """Run every bridge capability in order and report each one's verdict."""
    report = BridgeDiagnosisReport(expected_console_user=expected_console_user)
    if _probe_control_surfaces(report, run):
        probe_driven_window(report, run)
    report.close_unreached()
    passed = all(row["ok"] for row in report.rows)
    return HostActionResult(
        passed,
        {"operation": BRIDGE_DIAGNOSE_OPERATION, **report.evidence()},
        report.first_failure_code(),
    )


__all__ = ["diagnose_terminal_app_control"]
