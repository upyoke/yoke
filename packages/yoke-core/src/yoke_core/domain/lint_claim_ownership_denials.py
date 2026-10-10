"""Live-holder lookup and denial messages for claim ownership mutation lint."""

from __future__ import annotations

from datetime import timedelta
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.db_helpers import instant_parameter
from typing import Any, Callable, Optional

from yoke_core.domain.db_helpers import connect
from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none


RECENT_DENIAL_LOOKBACK_SECONDS = 1800


def recent_claim_denial_holder(
    db_path: Optional[str],
    session_id: str,
    item_ref: str,
    lookback_seconds: int = RECENT_DENIAL_LOOKBACK_SECONDS,
    *,
    connector: Callable[[Optional[str]], Any] = connect,
) -> Optional[str]:
    """Return the live foreign holder after a recent same-item claim attempt."""
    if not session_id:
        return None
    cutoff = utc_now() - timedelta(seconds=int(lookback_seconds))
    conn = None
    try:
        conn = connector(db_path or None)
        item_id = resolve_item_ref_or_none(conn, item_ref)
        if item_id is None:
            return None
        rows = conn.execute(
            "SELECT command_summary FROM session_tool_calls "
            "WHERE session_id=%s AND tool_name='Bash' "
            "AND command_summary IS NOT NULL "
            "AND started_at > %s ORDER BY started_at DESC LIMIT 100",
            (session_id, instant_parameter(conn, cutoff)),
        ).fetchall()
        item_tokens = {render_item_ref(conn, item_id), item_ref}
        attempted = any(
            isinstance(row[0], str)
            and "claim-work" in row[0]
            and any(tok in row[0] for tok in item_tokens)
            for row in rows
        )
        if not attempted:
            return None
        from yoke_core.domain.work_claim_targets import scope_int_sql

        item_scope = scope_int_sql(conn, "scope", "item_id")
        holder_row = conn.execute(
            "SELECT session_id FROM work_claims "
            f"WHERE target_kind='item' AND {item_scope}=%s "
            "AND released_at IS NULL AND claim_type='exclusive' "
            "AND session_id <> %s LIMIT 1",
            (item_id, session_id),
        ).fetchone()
        return holder_row[0] if holder_row else None
    except Exception:
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def spoof_reason(family: str, foreign_session: str) -> str:
    return attach_check_id(
        "BLOCKED: claim-boundary bypass attempt.\n\n"
        f"Mutation family: {family}\nForeign --session-id: {foreign_session}\n\n"
        "Artifact writes are work writes. Passing another session's id via "
        "--session-id from an ambient session is spoofing — the ambient "
        "session is the only valid owner. Foreign operator override for a "
        "stranded claim must use the operator break-glass release surface "
        "named in the Atlas.",
        check_id="lint-claim-ownership-mutations",
    )


def recent_denial_reason(family: str, public_ref: str, holder: str) -> str:
    return attach_check_id(
        "BLOCKED: claim-boundary bypass after live claim denial.\n\n"
        f"Mutation family: {family}\nItem: {public_ref}\n"
        f"Live holder: {holder}\n\n"
        "A recent claim-work in this session was denied with "
        "'already claimed by session' for the same item. Subsequent "
        f"mutating shapes against {public_ref} from this session are "
        "blocked until the holder releases or hands off.",
        check_id="lint-claim-ownership-mutations",
    )


__all__ = [
    "RECENT_DENIAL_LOOKBACK_SECONDS",
    "recent_claim_denial_holder",
    "recent_denial_reason",
    "spoof_reason",
]
