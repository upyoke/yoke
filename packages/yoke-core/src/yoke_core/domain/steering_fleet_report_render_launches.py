"""Render the two launch findings, each naming what to do about it.

Both rows exist because a launch can fail in a way nothing else surfaces: one
never bound to a session, the other bound and then lost its worker. Neither
is readable without the native's own words, and the capture holding them sits
on the machine that produced it — so the last line the native said travels on
the row itself, for every seat that cannot reach that machine.
"""

from __future__ import annotations

from yoke_contracts.session_control.evidence_fetch import evidence_pull_suffix
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


def _unregistered_line(entry: UnregisteredLaunch) -> str:
    native = entry.observed_session_id or entry.native_session_id
    died = bool(entry.native_stderr_tail or entry.exit_code)
    if native and not died:
        # The native is up and answering; only the binding is missing.
        problem = f"registered session {native} exists; launch binding is absent"
        recovery = (
            "native is live — bind it: `yoke session-control launch reconcile "
            f"{entry.launch_id} --observed-native-id {native}`"
        )
    elif native:
        problem = f"native for session {native} exited before binding"
        recovery = (
            "native is dead — reconcile, then retry: `yoke session-control launch "
            f"reconcile {entry.launch_id} --observed-native-id {native}`"
        )
    elif entry.result_code in CORRELATION_FAILURE_CODES:
        problem = entry.result_code.replace("_", " ")
        recovery = (
            "native is dead — reconcile, then retry: find the native session ID, "
            f"then `yoke session-control launch reconcile {entry.launch_id} "
            "--observed-native-id ID`"
        )
    elif entry.result_code == "model_combo_unsupported":
        problem = entry.detail or "native CLI rejected the requested combination"
        recovery = "choose a supported model, effort, and context combination"
    else:
        problem = f"{entry.state}, deadline overdue {minutes(entry.overdue_seconds)}"
        recovery = "inspect registration before retry"
    if entry.native_launch_pid and entry.native_launch_phase:
        problem += f", native pid {entry.native_launch_pid} {entry.native_launch_phase}"
    if entry.spawn_duration_ms is not None:
        problem += f", spawn {entry.spawn_duration_ms / 1000:.1f}s"
    problem += _said(entry.native_stderr_tail, entry.exit_code)
    # The tail above is one line; the whole capture stays on the machine that
    # wrote it, and this is the read that brings it to a seat elsewhere.
    recovery += evidence_pull_suffix(native, entry.evidence_id)
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
