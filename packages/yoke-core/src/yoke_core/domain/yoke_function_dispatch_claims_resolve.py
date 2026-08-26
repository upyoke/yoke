"""Server-side claim-id lookup for ``self_only`` release envelopes.

Keeps the dispatcher claim-verification module under the authored-file
line budget while covering item, epic_task, and process shaped targets.
Filtering on ``session_id = actor_session`` makes the lookup itself the
self-ownership proof (relay contract — clients never pre-read
``work_claims``).
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.work_claim_targets import (
    exact_match_clause,
    make_epic_task_target,
    make_item_target,
    make_process_target,
)


def _placeholder(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def claim_row_for_id(claim_id: int) -> Optional[dict[str, Any]]:
    try:
        from yoke_core.domain import db_helpers

        with db_helpers.connect() as conn:
            p = _placeholder(conn)
            row = conn.execute(
                "SELECT id, session_id, target_kind "
                "FROM work_claims "
                f"WHERE id = {p} AND released_at IS NULL",
                (int(claim_id),),
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    return {
        "id": row[0],
        "session_id": row[1],
        "operational_session_id": row[1],
        "target_kind": row[2],
    }


def session_claim_id_for_target(
    target: Any,
    actor_session: str,
    *,
    process_key: Optional[str] = None,
    project: Optional[str] = None,
) -> Optional[int]:
    """Resolve the calling session's active claim id for a self_only target.

    Item and epic_task shapes read from ``target``; process shapes pass
    ``process_key`` + ``project`` (conflict group is registry-computed).
    """
    if not actor_session:
        return None
    try:
        from yoke_core.domain import db_helpers

        with db_helpers.connect() as conn:
            p = _placeholder(conn)
            if process_key:
                claim_target = make_process_target(
                    str(process_key).strip().upper(),
                    (project or "yoke").strip() or "yoke",
                )
            elif target.kind == "item" and target.item_id is not None:
                claim_target = make_item_target(int(target.item_id))
            elif (
                target.kind == "epic_task"
                and target.epic_id is not None
                and target.task_num is not None
            ):
                claim_target = make_epic_task_target(
                    int(target.epic_id), int(target.task_num)
                )
            else:
                return None
            match, params = exact_match_clause(conn, claim_target)
            row = conn.execute(
                "SELECT id FROM work_claims "
                f"WHERE session_id = {p} AND {match} "
                "AND released_at IS NULL ORDER BY id DESC LIMIT 1",
                (actor_session, *params),
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    return int(row[0] if not hasattr(row, "keys") else row["id"])


__all__ = ["claim_row_for_id", "session_claim_id_for_target"]
