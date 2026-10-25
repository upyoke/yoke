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
from collections.abc import Mapping, Sequence
from typing import Any

from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.fleet_watcher_observation import (
    observed_absent,
    observed_lapsed_tail,
)
from yoke_contracts.harness_wake_capability import wake_capability_for_harness
from yoke_contracts.hook_context_compose import ALERT_BEGIN, ALERT_END
from yoke_core.domain.session_mode import session_is_parked
from yoke_core.hooks.types import HookContext


_REARM = "yoke watch fleet --print-streaming-pair --"
_TURN_START_EVENT = "UserPromptSubmit"


def _dispatch(function_id: str, payload: dict[str, Any]) -> Any:
    """Read over the active control-plane transport as this hook's actor."""
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        build_actor,
        call_dispatcher,
    )

    return call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        actor=build_actor(),
    )


def _session_row(session_id: str) -> Mapping[str, Any] | None:
    """Read pause and lifecycle authority over the active control-plane transport."""
    response = _dispatch("sessions.list", {"session_id": session_id})
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


def _seat_listing(session_id: str) -> str:
    return f"yoke claims steering list --session-id {shlex.quote(session_id)} --active-only"


def held_projects(session_id: str) -> tuple[str, ...]:
    """Return each project this session holds a live steering seat in, once.

    The session's own steering list spans every project, so a seat outside
    the hook's project still counts. Document seats in one project share it.
    """
    response = _dispatch(
        "claims.steering.list", {"session_id": session_id, "active_only": True}
    )
    if not response.success:
        error = response.error
        raise RuntimeError(f"{error.code}: {error.message}" if error else "no reason given")
    return tuple(
        dict.fromkeys(
            str(claim["scope"]["project_id"])
            for claim in response.result.get("claims", [])
        )
    )


def lapsed_tail_nudge(executor_family: str, lapsed_capture: str) -> str:
    """Re-arm a lapsed subscription on the live wrapper's capture, or nothing."""
    wake = wake_capability_for_harness(canonical_harness_id(executor_family))
    limit = wake.idle_wake_subscription_limit_seconds
    if not (lapsed_capture and limit):
        return ""
    return (
        f"Fleet watcher's {wake.idle_wake_mechanism} subscription expired "
        "while its wrapper still runs. Re-arm the same tail against the "
        f"same capture with {wake.idle_wake_deadline_parameter}="
        f"{limit * 1000}: `yoke watch tail {shlex.quote(lapsed_capture)}`. "
        "Never relaunch the wrapper; a second one doubles every report."
    )


def fleet_watcher_absent_nudge(
    projects: Sequence[str], session_id: str, executor_family: str, event_name: str
) -> str:
    """Name the gap and the exact re-arm recipe for this harness's wake model."""
    wake = wake_capability_for_harness(canonical_harness_id(executor_family))
    if not projects:
        return (
            "Fleet watcher is not running, and this session holds no steering "
            f"seats, so there is nothing to watch: `{_seat_listing(session_id)}` "
            "confirms it. Take a seat with `yoke claims steering acquire "
            "--project P` before re-arming."
        )
    flags = " ".join(f"--project {shlex.quote(project)}" for project in projects)
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
        f"`{_REARM} {flags}`.{recipe}"
    )


def _absent_line(session_id: str, context: HookContext) -> str:
    try:
        projects = held_projects(session_id)
    except Exception as exc:  # The alert still names the gap and the manual read.
        return (
            "Fleet watcher is not running for this session, and reading its "
            f"steering seats failed ({exc}). List them with "
            f"`{_seat_listing(session_id)}`, then re-arm with "
            f"`{_REARM} --project P` once per held project."
        )
    return fleet_watcher_absent_nudge(
        projects, session_id, context.executor_family, context.event_name
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
    line = lapsed_tail_nudge(
        context.executor_family, observed_lapsed_tail(context.payload, session_id)
    ) or _absent_line(session_id, context)
    return f"{ALERT_BEGIN}\n{line}\n{ALERT_END}"

__all__ = [
    "fleet_watcher_absent_nudge",
    "fleet_watcher_alert",
    "held_projects",
    "lapsed_tail_nudge",
]
