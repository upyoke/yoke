"""Choose whether a watcher may release its caller's model turn.

The background streaming shape is safe only when the current session can be
resumed after watcher output or completion.  The session roster already owns
that reachability answer, while the harness wake registry owns whether the
model-facing runtime has an idle-wake primitive.  A missing fact holds the
turn: waiting too long is recoverable; returning to a caller that cannot be
woken is not.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable, Literal, Mapping

from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.harness_wake_capability import wake_capability_for_harness
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV


WaitModeName = Literal["background-wake", "in-turn"]


@dataclass(frozen=True)
class WatchWaitMode:
    """One selected wait shape and the evidence that selected it."""

    name: WaitModeName
    reason: str
    wake_mechanism: str = ""

    @property
    def waits_in_turn(self) -> bool:
        return self.name == "in-turn"


def _in_turn(reason: str) -> WatchWaitMode:
    return WatchWaitMode(name="in-turn", reason=reason)


def _background(reason: str, mechanism: str) -> WatchWaitMode:
    return WatchWaitMode(
        name="background-wake",
        reason=reason,
        wake_mechanism=mechanism,
    )


def wait_mode_for_session(row: Mapping[str, Any] | None) -> WatchWaitMode:
    """Choose a wait mode from one complete ``sessions.list`` roster row."""
    if row is None:
        return _in_turn(
            "session reachability is unknown because sessions.list returned no row"
        )

    executor = str(row.get("executor") or "").strip()
    try:
        harness_id = canonical_harness_id(executor)
    except ValueError:
        return _in_turn(
            f"session reachability is unknown for executor {executor or '<empty>'}"
        )

    wake = wake_capability_for_harness(harness_id)
    if wake.idle_wake == "none":
        return _in_turn(f"{harness_id} records agent_wake.idle_wake=none")
    if wake.idle_wake != "supported":
        return _in_turn(f"{harness_id} agent_wake.idle_wake is unverified")

    routing = row.get("messageability")
    if not isinstance(routing, Mapping):
        return _in_turn(
            "session reachability is unknown because messageability is absent"
        )
    surface = str(row.get("executor_surface") or "unknown-surface")
    if routing.get("wake_authority") == "operator":
        return _in_turn(
            f"{surface} is operator-woken and has no autonomous completion wake"
        )

    available = routing.get("wake_available")
    route_reason = str(routing.get("reason") or "unspecified")
    if available is True:
        return _background(
            f"sessions.list reports a reachable wake route for {surface}",
            wake.idle_wake_mechanism,
        )
    if available is False and route_reason not in {
        "unknown_surface",
        "version_below_floor_or_unknown",
    }:
        return _in_turn(
            f"sessions.list reports no wake route for {surface} ({route_reason})"
        )
    return _in_turn(f"session reachability is unknown for {surface} ({route_reason})")


def _current_session_row() -> Mapping[str, Any] | None:
    """Read this caller's authoritative roster projection."""
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        build_actor,
        call_dispatcher,
    )

    actor = build_actor()
    if not actor.session_id:
        return None
    response = call_dispatcher(
        function_id="sessions.list",
        target=TargetRef(kind="global"),
        payload={"session_id": actor.session_id},
        actor=actor,
        intent="choose watcher wait mode from caller reachability",
    )
    if not response.success:
        return None
    rows = response.result.get("rows")
    if not isinstance(rows, list):
        return None
    return next(
        (
            row
            for row in rows
            if isinstance(row, Mapping)
            and str(row.get("session_id") or "") == actor.session_id
        ),
        None,
    )


def resolve_wait_mode(
    *,
    environ: Mapping[str, str] | None = None,
    session_reader: Callable[[], Mapping[str, Any] | None] = _current_session_row,
) -> WatchWaitMode:
    """Resolve the current caller, failing closed to an in-turn wait."""
    source = os.environ if environ is None else environ
    if str(source.get(LAUNCH_CONTEXT_ENV) or "").strip():
        return _in_turn("relay launch context marks this caller as a headless command")
    try:
        row = session_reader()
    except Exception as exc:  # noqa: BLE001 - unknown reachability waits safely
        return _in_turn(
            "session reachability lookup failed "
            f"({type(exc).__name__}); keeping the wait in this turn"
        )
    return wait_mode_for_session(row)


__all__ = [
    "WatchWaitMode",
    "resolve_wait_mode",
    "wait_mode_for_session",
]
