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
    """``True`` live (active or stale), ``False`` ended, ``None`` unknown.

    Unknown covers an unregistered id, a transport failure, and any error:
    the healer keeps unknown contenders, so failure stays fail-closed.
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
        return None
    return str(rows[0].get("liveness") or "") != "ended"


__all__ = ["contender_is_live"]
