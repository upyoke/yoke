"""Transport guard for client-side event emission.

When the active control-plane connection is https, opening a local Postgres
connection raises, so client-side event emission must degrade to a non-ok
result rather than a fatal error. Domain-critical events are emitted
server-side by the relayed registered functions, so dropping client
telemetry over https is acceptable.
"""

from __future__ import annotations

# Reason recorded on an ``EmitResult`` when client-side emission is skipped
# because the active control-plane connection is https and no local
# connection was supplied. Callers that would otherwise treat a non-ok
# emission as fatal consult this to keep telemetry best-effort over https.
TRANSPORT_NO_LOCAL_DB_REASON = "transport_no_local_db"


def _active_transport_is_https() -> bool:
    """Return whether the active control-plane connection uses https.

    Reuses the same detection the worktree-creation relay uses so there is
    one https-transport check. Best-effort: any failure to resolve the
    connection is treated as "not https".
    """
    try:
        from yoke_core.domain.worktree_create_db import (
            item_worktree_authority_is_https,
        )

        return item_worktree_authority_is_https()
    except Exception:
        return False


__all__ = ["TRANSPORT_NO_LOCAL_DB_REASON", "_active_transport_is_https"]
