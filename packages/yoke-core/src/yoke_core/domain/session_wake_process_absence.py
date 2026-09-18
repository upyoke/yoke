"""The one hook-route absence a machine reported rather than a clock inferred.

Its sibling :mod:`session_message_starvation` decides from clocks: how long a
recipient has been silent, what posture it declared, what its harness can do
about that. Every one of those is an inference about a process nobody looked
at. This one is not an inference. The machine that started the native watched
it exit, reported the death, and the control plane stored it on the session.

A recipient in that state has no hook coming, because a hook runs on a tool
call and there is no process left to make one. So there is nothing to wait
out, and the acknowledgement grace window that guards the inferred absences
would only postpone the resume that is the sole way in. Six item-QA envelopes
went out to recipients whose processes were already recorded gone and none
reached a session for ten to fourteen minutes.

Liveness does not catch this on its own. A session whose heartbeat is still
inside the liveness window reads ``active`` while its process is recorded
gone -- the heartbeat outlives the process that stopped refreshing it -- and
an ``active`` recipient is handed to the hook route it no longer has.

The verdict itself is not re-derived here. The reader this calls is the one
the fleet report's undelivered rows already use, so an escalation from here
and a ``gone`` row there can never disagree, and its own rule -- that later
activity retires the death -- is what keeps a session that has since been
resumed from being escalated over a stale report.

Escalating is still only a proposal. The machine that would start the second
native checks its own custody records first, in
:mod:`yoke_harness.session_relay_native_turn_custody`, and refuses when it is
already running one for that session.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping

from yoke_contracts.session_control.surface_versions import (
    surface_operation_supported,
)
from yoke_core.domain.session_message_starvation import (
    awaiting_injection,
    escalated_wake_available,
)
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)


#: Recorded on the receipt and wake attempt this escalation authorized,
#: beside the two inferred absences its sibling module names.
NATIVE_PROCESS_GONE = "native_process_gone"


def native_process_gone(
    row: Mapping[str, Any],
    *,
    grace_seconds: int,
    now: datetime,
    ignore_wake_cooldown: bool = False,
) -> bool:
    """True when this recipient's process is recorded gone and unaccounted for.

    ``row`` is one eligibility row: the recipient joined to its message and
    its session. No waiting window is consulted before the first wake, for
    the reason this module exists -- the absence was observed, not inferred,
    and it does not become truer by waiting. ``grace_seconds`` therefore only
    spaces repeat wakes apart, and ``ignore_wake_cooldown`` suspends even
    that for the caller re-deriving a candidate whose wake it has already
    stamped.

    The surface test reads the recipient's own capability rather than the
    same-machine peer that could execute a resume, so a desktop or IDE
    conversation -- one declaring ``wake_authority: operator`` -- is never
    resumed into a forked transcript, however dead its process is.
    """
    if not awaiting_injection(row):
        return False
    if current_native_process_observation(row) is None:
        return False
    if not surface_operation_supported(
        str(row.get("executor_surface") or ""),
        str(row.get("executor_version") or "") or None,
        "message_stopped",
    ):
        return False
    return escalated_wake_available(
        row,
        window=timedelta(seconds=grace_seconds),
        now=now,
        ignore_wake_cooldown=ignore_wake_cooldown,
    )


__all__ = ["NATIVE_PROCESS_GONE", "native_process_gone"]
