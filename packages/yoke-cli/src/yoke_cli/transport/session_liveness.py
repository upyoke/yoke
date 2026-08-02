"""Point probe: is one session live, ended, or unknown?

The anchor-contention healer (:mod:`yoke_contracts.session_anchor_contention`)
drops a recorded contender only on a positive answer that its session ended.
This probe supplies that answer over whichever transport the machine uses,
via the ``sessions.list`` single-session projection — a stale session counts
as live, because a quiet conversation's background children still run under
its identity.

Lives in the transport layer so both anchor writers — the engine-side shim
and the harness hook client — share one implementation.
"""

from __future__ import annotations

from typing import Optional

from yoke_contracts.api.function_call import TargetRef


def contender_is_live(session_id: str) -> Optional[bool]:
    """``True`` live (active or stale), ``False`` not a live session, ``None`` unknown.

    A successful probe that finds *no row* answers ``False``: session rows
    are never deleted — ended conversations keep theirs — so an id with
    positively no registration is not a conversation on this control plane
    (the anchor-poisoning class is exactly such ids). The one race, a
    brand-new session probed before its first registration flush, self
    corrects: its next anchor write re-contends the pid. ``None`` is
    reserved for a failed probe — transport down, refused call — which the
    healer keeps, so genuine ambiguity stays fail-closed.
    """
    if not session_id:
        return None
    try:
        from yoke_cli.transport.dispatcher import call_dispatcher

        response = call_dispatcher(
            function_id="sessions.list",
            target=TargetRef(kind="global"),
            payload={"session_id": session_id},
        )
    except Exception:  # noqa: BLE001 — probe failure is "unknown"
        return None
    if not response.success:
        return None
    rows = (response.result or {}).get("rows") or []
    if not rows:
        return False
    return str(rows[0].get("liveness") or "") != "ended"


__all__ = ["contender_is_live"]
