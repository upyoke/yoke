"""Render the two launch findings, each naming what to do about it.

Both rows exist because a launch can fail in a way nothing else surfaces: one
never bound to a session, the other bound and then lost its worker. Neither
is readable without the native's own words, and the capture holding them sits
on the machine that produced it — so the last line the native said travels on
the row itself, for every seat that cannot reach that machine.
"""

from __future__ import annotations

from yoke_contracts.session_control.launch_registration import (
    NATIVE_EXITED_UNREGISTERED_CODE,
)
from yoke_core.domain.session_launch_reconciliation import (
    RECONCILABLE_LAUNCH_STATES,
)
from yoke_core.domain.session_launch_visibility import CORRELATION_FAILURE_CODES
from yoke_core.domain.steering_fleet_report_abandoned import AbandonedLaunch
from yoke_core.domain.steering_fleet_report_detectors import UnregisteredLaunch
from yoke_core.domain.steering_fleet_report_render_text import (
    SECTION_LIMIT,
    capped,
    minutes,
)


def _said(tail: str, exit_code: int | None) -> str:
    if tail and exit_code is not None:
        return f"; exit {exit_code}, last output: {tail}"
    if tail:
        return f"; last output: {tail}"
    if exit_code is not None:
        return f"; exit {exit_code}, no output"
    return ""


_RELAUNCH = "relaunch once the cause is fixed"
_UNBINDABLE = (
    "no command binds it in this state; relaunch once the native exits "
    "and the cause is fixed"
)


def _bind_recovery(
    entry: UnregisteredLaunch, native: str | None, died: bool
) -> str:
    # Reconcile refuses every other state, so offering it there only fails.
    if entry.state not in RECONCILABLE_LAUNCH_STATES:
        return _UNBINDABLE
    command = (
        f"`yoke session-control launch reconcile {entry.launch_id} "
        f"--observed-native-id {native or 'ID'}`"
    )
    if native is None:
        command = f"find the native session ID, then {command}"
    if died:
        return f"native is dead — reconcile, then retry: {command}"
    return f"native is live — bind it: {command}"


def _unregistered_line(entry: UnregisteredLaunch) -> str:
    native = entry.observed_session_id or entry.native_session_id
    died = bool(entry.native_stderr_tail or entry.exit_code)
    if entry.result_code == NATIVE_EXITED_UNREGISTERED_CODE:
        # The machine that started this native watched it go, so the launch
        # is already closed: there is no binding left to reconcile.
        problem = "native exited before any session registered"
        recovery = _RELAUNCH
    elif entry.result_code == "reconciled_not_created" and not native:
        # Reconcile already settled that no native exists; another pass
        # changes nothing.
        problem = "reconciled as never created"
        recovery = _RELAUNCH
    elif native:
        if died:
            problem = f"native for session {native} exited before binding"
        elif entry.observed_session_id:
            problem = f"registered session {native} exists; launch binding is absent"
        else:
            problem = f"native session {native} started; no session registered"
        recovery = _bind_recovery(entry, native, died)
    elif entry.result_code in CORRELATION_FAILURE_CODES:
        problem = entry.result_code.replace("_", " ")
        recovery = _bind_recovery(entry, None, True)
    elif entry.result_code == "model_combo_unsupported":
        problem = entry.detail or "native CLI rejected the requested combination"
        recovery = "choose a supported model, effort, and context combination"
    else:
        problem = f"{entry.state}, deadline overdue {minutes(entry.overdue_seconds)}"
        recovery = "inspect registration before retry"
    if entry.state == "failed":
        recovery += (
            "; if resolved or no longer needed, settle it: "
            f"`yoke session-control launch cancel {entry.launch_id}`"
        )
    if entry.native_launch_pid and entry.native_launch_phase:
        problem += f", native pid {entry.native_launch_pid} {entry.native_launch_phase}"
    if entry.spawn_duration_ms is not None:
        problem += f", spawn {entry.spawn_duration_ms / 1000:.1f}s"
    output = " ".join((entry.native_stderr_excerpt or entry.native_stderr_tail).split())
    if len(output) > 512:
        output = "…" + output[-511:]
    problem += _said(output, entry.exit_code)
    return (
        f"  launch {entry.launch_id}  {entry.surface} on {entry.machine_id}  "
        f"{problem}; instruction not delivered; {recovery}"
    )


def _abandoned_line(entry: AbandonedLaunch) -> str:
    session = entry.session_id or "unknown session"
    return (
        f"  launch {entry.launch_id}  {entry.surface} on {entry.machine_id}  "
        f"session {session} read its mandate and never started, closed "
        f"{minutes(entry.closed_seconds)} ago"
        f"{_said(entry.native_stderr_tail, entry.exit_code)}; "
        "its work is unstarted — restaff it"
    )


def unregistered_launch_lines(
    entries: tuple[UnregisteredLaunch, ...],
) -> list[str]:
    """One line per launch whose instruction is stranded, with its recovery."""
    return capped(
        [_unregistered_line(entry) for entry in entries[:SECTION_LIMIT]],
        len(entries),
    )


def abandoned_launch_lines(entries: tuple[AbandonedLaunch, ...]) -> list[str]:
    """One line per launch whose worker died before it began its mandate."""
    return capped(
        [_abandoned_line(entry) for entry in entries[:SECTION_LIMIT]],
        len(entries),
    )


__all__ = ["abandoned_launch_lines", "unregistered_launch_lines"]
