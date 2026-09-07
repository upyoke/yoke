"""Client-side detection of a steering session's standing fleet watcher.

The fleet report is composed server-side and injected by the local hook.
That injection keeps arriving even when the standing watcher that is
supposed to arm the seat has died — so the gap is invisible unless this
machine says so. Detection is process-listing only: the wrapper runs
``yoke_core.domain.fleet_delta_probe`` with captures under the session's
scratch run directory. No pidfile is added; none already exists.
"""

from __future__ import annotations

import subprocess
import shlex
from collections.abc import Mapping, Sequence
from typing import Any

from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.harness_wake_capability import wake_capability_for_harness
from yoke_core.domain.session_mode import session_is_parked


# Keep equal to yoke_core.tools.watch_fleet.{PROBE_MODULE, WRAPPER_MODULE, KIND}.
PROBE_MODULE = "yoke_core.domain.fleet_delta_probe"
WRAPPER_MODULE = "yoke_core.tools.watch_fleet"
CAPTURE_KIND = "fleet"

_REARM = "yoke watch fleet --print-streaming-pair --"


def _session_row(session_id: str) -> Mapping[str, Any] | None:
    """Read pause and lifecycle authority over the active control-plane transport."""
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        build_actor,
        call_dispatcher,
    )

    response = call_dispatcher(
        function_id="sessions.list",
        target=TargetRef(kind="global"),
        payload={"session_id": session_id},
        actor=build_actor(),
    )
    if not response.success:
        return None
    return next(
        (
            row
            for row in response.result.get("rows", [])
            if isinstance(row, Mapping) and row.get("session_id") == session_id
        ),
        None,
    )


def list_process_cmdlines() -> tuple[str, ...]:
    """Return this machine's process command lines, or empty on failure."""
    try:
        completed = subprocess.run(
            ["ps", "-ax", "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if completed.returncode != 0:
        return ()
    return tuple(completed.stdout.splitlines())


def session_fleet_watcher_alive(
    session_id: str,
    cmdlines: Sequence[str],
) -> bool:
    """True when a live probe and this session's fleet capture path are listed."""
    if not session_id:
        return False
    marker = f"/sessions/{session_id}/"
    capture_token = f"yoke-{CAPTURE_KIND}."
    has_probe = any(PROBE_MODULE in line for line in cmdlines)
    has_session_capture = any(
        marker in line
        and (PROBE_MODULE in line or WRAPPER_MODULE in line or capture_token in line)
        for line in cmdlines
    )
    return has_probe and has_session_capture


def _project_flags(report: str) -> str:
    projects = dict.fromkeys(
        line[3:].split(" · ", 1)[0].strip()
        for line in report.splitlines()
        if line.startswith("## ") and not line.startswith("### ")
    )
    if not projects:
        return "--project <held scopes>"
    return " ".join(f"--project {shlex.quote(project)}" for project in projects)


def fleet_watcher_absent_nudge(report: str, executor_family: str) -> str:
    """One line naming the gap and the exact re-arm recipe."""
    wake = wake_capability_for_harness(canonical_harness_id(executor_family))
    recipe = (
        " Follow the returned wait_mode; use only its declared native subscription."
    )
    if executor_family == "codex" and wake.idle_wake != "supported":
        recipe = (
            " Keep the in-turn exec_command/write_stdin stream active; answer ordinary "
            "questions in commentary and continue. An ended desktop turn has no native "
            "background notification."
        )
    return (
        "Fleet watcher is not running for this session; re-arm with "
        f"`{_REARM} {_project_flags(report)}`.{recipe}"
    )


def maybe_append_fleet_watcher_nudge(
    report: str,
    *,
    session_id: str,
    executor_family: str,
    remote: bool,
    cmdlines: Sequence[str] | None = None,
) -> str:
    """Nudge an active steering session whose local watcher is gone.

    Remote evaluations cannot see this machine's process table, so they
    leave the composed report unchanged rather than inventing a gap.
    A process-list failure is the same: absence is not proven.
    """
    if remote or not report or not session_id:
        return report
    listed = list_process_cmdlines() if cmdlines is None else cmdlines
    if not listed:
        return report
    if session_fleet_watcher_alive(session_id, listed):
        return report
    try:
        row = _session_row(session_id)
    except Exception:  # A failed posture read never overrides an explicit pause.
        row = None
    if row is None:
        line = (
            "Fleet watcher posture is unreadable; check `yoke sessions list --json` "
            "before re-arming, preserving an explicit parked/stop request."
        )
    elif (
        session_is_parked(row.get("mode"))
        or row.get("ended_at")
        or row.get("terminated_at")
    ):
        return report
    else:
        line = fleet_watcher_absent_nudge(report, executor_family)
    prefix = "" if report.endswith("\n") else "\n"
    return f"{report}{prefix}{line}"


__all__ = [
    "CAPTURE_KIND",
    "PROBE_MODULE",
    "WRAPPER_MODULE",
    "fleet_watcher_absent_nudge",
    "list_process_cmdlines",
    "maybe_append_fleet_watcher_nudge",
    "session_fleet_watcher_alive",
]
