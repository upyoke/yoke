"""Choose whether a watcher may release its caller's model turn.

The background streaming shape is safe only when the model-facing runtime can
resume a turn that has already ended.  That is a property of the harness the
conversation runs in — its own native background-command notification
primitive — so the harness wake registry is the sole authority for an
interactive caller.  Yoke's ability to reach the session over a relay is a
different question and does not gate this one: Claude's ``Monitor`` and
Cursor's ``notify_on_output`` resume the turn in place, needing nothing from
the control plane.  The registry records capability per harness family, so a
desktop conversation selects exactly what its CLI sibling does.

A relay-launched worker is the one caller that cannot be resumed in place,
because it is a headless command whose turn is its whole life.  That case is
settled from the launch context before any harness fact is read.

A missing fact holds the turn: waiting too long is recoverable; returning to a
caller that cannot be woken is not.
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
    """Choose a wait mode from the harness named by one roster row."""
    if row is None:
        return _in_turn(
            "harness identity is unknown because sessions.list returned no row"
        )

    executor = str(row.get("executor") or "").strip()
    try:
        harness_id = canonical_harness_id(executor)
    except ValueError:
        return _in_turn(
            f"harness identity is unknown for executor {executor or '<empty>'}"
        )

    wake = wake_capability_for_harness(harness_id)
    if wake.idle_wake == "none":
        return _in_turn(f"{harness_id} records agent_wake.idle_wake=none")
    if wake.idle_wake != "supported":
        return _in_turn(f"{harness_id} agent_wake.idle_wake is unverified")
    return _background(
        f"{harness_id} records agent_wake.idle_wake=supported "
        f"via {wake.idle_wake_mechanism}",
        wake.idle_wake_mechanism,
    )


def _current_session_row() -> Mapping[str, Any] | None:
    """Read the roster row that names which harness this caller runs in."""
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
        intent="choose watcher wait mode from the caller's harness",
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
    except Exception as exc:  # noqa: BLE001 - an unknown harness waits safely
        return _in_turn(
            "harness identity lookup failed "
            f"({type(exc).__name__}); keeping the wait in this turn"
        )
    return wait_mode_for_session(row)


__all__ = [
    "WatchWaitMode",
    "resolve_wait_mode",
    "wait_mode_for_session",
]
