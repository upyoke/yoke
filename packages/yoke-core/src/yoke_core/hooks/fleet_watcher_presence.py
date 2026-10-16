"""Alert a steering session whose standing fleet watcher is gone.

The fleet report is composed where the hook chain evaluates — the server over
HTTPS, this process in a local universe. That injection keeps arriving even
when the watcher that is supposed to arm the seat has died, so the gap is
invisible unless the harness's own machine says so. That machine makes the
one presence check (:mod:`yoke_contracts.fleet_watcher_observation`) and
ships it with the hook request. This module only renders: it never claims
absence the client did not prove, and an unreadable posture stays silent.

The alert is its own context block, not a line inside the report, so the
byte ceiling that drops the report keeps the alert.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from typing import Any

from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.fleet_watcher_observation import observed_absent
from yoke_contracts.harness_wake_capability import wake_capability_for_harness
from yoke_contracts.hook_context_compose import ALERT_BEGIN, ALERT_END
from yoke_core.domain.session_mode import session_is_parked
from yoke_core.hooks.types import HookContext


_REARM = "yoke watch fleet --print-streaming-pair --"
_TURN_START_EVENT = "UserPromptSubmit"


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


def _project_flags(report: str) -> str:
    projects = dict.fromkeys(
        line[3:].split(" · ", 1)[0].strip()
        for line in report.splitlines()
        if line.startswith("## ") and not line.startswith("### ")
    )
    if not projects:
        return "--project <held scopes>"
    return " ".join(f"--project {shlex.quote(project)}" for project in projects)


def fleet_watcher_absent_nudge(
    report: str, executor_family: str, event_name: str
) -> str:
    """Name the gap and the exact re-arm recipe for this harness's wake model."""
    wake = wake_capability_for_harness(canonical_harness_id(executor_family))
    recipe = (
        " That prints the invocation and starts nothing; run it, using only "
        "the native subscription its wait_mode declares."
    )
    if wake.idle_wake == "none":
        recipe = (
            " That prints the invocation and starts nothing; run the printed "
            "in-turn command and keep its exec_command/write_stdin stream "
            "active; answer ordinary questions in commentary and continue. An "
            "ended desktop turn has no native background notification."
        )
        if event_name == _TURN_START_EVENT:
            recipe += (
                " Between turns, desktop re-entry is the `keep steering` "
                "scheduled task in `.agents/skills/yoke/steer/watching.md`."
            )
    return (
        "Fleet watcher is not running for this session; re-arm with "
        f"`{_REARM} {_project_flags(report)}`.{recipe}"
    )


def fleet_watcher_alert(report: str, context: HookContext) -> str:
    """Return the alert block for an active steering session, or nothing."""
    session_id = str(context.session_id or "")
    if not report or not observed_absent(context.payload, session_id):
        return ""
    try:
        row = _session_row(session_id)
    except Exception:  # A failed posture read never overrides an explicit pause.
        return ""
    if (
        row is None
        or session_is_parked(row.get("mode"))
        or row.get("ended_at")
        or row.get("terminated_at")
    ):
        return ""
    line = fleet_watcher_absent_nudge(
        report, context.executor_family, context.event_name
    )
    return f"{ALERT_BEGIN}\n{line}\n{ALERT_END}"


__all__ = ["fleet_watcher_absent_nudge", "fleet_watcher_alert"]
