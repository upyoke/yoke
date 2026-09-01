"""Client-side detection of a steering session's standing fleet watcher.

The fleet report is composed server-side and injected by the local hook.
That injection keeps arriving even when the idle-wake watcher that is
supposed to arm the seat has died — so the gap is invisible unless this
machine says so. Detection is process-listing only: the wrapper runs
``yoke_core.domain.fleet_delta_probe`` with captures under the session's
scratch run directory. No pidfile is added; none already exists.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

from yoke_contracts.harness_wake_capability import wake_capability_for_harness


# Keep equal to yoke_core.tools.watch_fleet.{PROBE_MODULE, WRAPPER_MODULE, KIND}.
PROBE_MODULE = "yoke_core.domain.fleet_delta_probe"
WRAPPER_MODULE = "yoke_core.tools.watch_fleet"
CAPTURE_KIND = "fleet"

_REARM = "yoke watch fleet --print-streaming-pair --"


def harness_id_for_family(executor_family: str) -> str:
    """Map a hook family onto the wake-capability harness id."""
    return "claude-code" if executor_family == "claude" else executor_family


def family_has_idle_wake(executor_family: str) -> bool:
    """Whether this family declares an idle-wake primitive."""
    return (
        wake_capability_for_harness(harness_id_for_family(executor_family)).idle_wake
        == "supported"
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
    scopes = [
        line[3:].strip()
        for line in report.splitlines()
        if line.startswith("## ") and not line.startswith("### ")
    ]
    if not scopes:
        return "--project <held scopes>"
    return " ".join(f"--project {scope}" for scope in scopes)


def fleet_watcher_absent_nudge(report: str) -> str:
    """One line naming the gap and the exact re-arm recipe."""
    return (
        "Fleet watcher is not running for this session; re-arm with "
        f"`{_REARM} {_project_flags(report)}`."
    )


def maybe_append_fleet_watcher_nudge(
    report: str,
    *,
    session_id: str,
    executor_family: str,
    remote: bool,
    cmdlines: Sequence[str] | None = None,
) -> str:
    """Append the one-line nudge when this machine's idle-wake watcher is gone.

    Remote evaluations cannot see this machine's process table, so they
    leave the composed report unchanged rather than inventing a gap.
    A process-list failure is the same: absence is not proven.
    """
    if remote or not report or not session_id:
        return report
    if not family_has_idle_wake(executor_family):
        return report
    listed = list_process_cmdlines() if cmdlines is None else cmdlines
    if not listed:
        return report
    if session_fleet_watcher_alive(session_id, listed):
        return report
    line = fleet_watcher_absent_nudge(report)
    prefix = "" if report.endswith("\n") else "\n"
    return f"{report}{prefix}{line}"


__all__ = [
    "CAPTURE_KIND",
    "PROBE_MODULE",
    "WRAPPER_MODULE",
    "family_has_idle_wake",
    "fleet_watcher_absent_nudge",
    "harness_id_for_family",
    "list_process_cmdlines",
    "maybe_append_fleet_watcher_nudge",
    "session_fleet_watcher_alive",
]
