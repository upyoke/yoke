"""Which steering groups are live, as a question of its own.

A steering group is the set of sessions a single steering seat covers, and
consumers that only need to *distinguish* the groups — the app's card tint
is the one today — need nothing about the sessions in them. They need the
identity of each live seat.

That is a fact about live steering claims, so this read asks
``work_claims`` directly through the one central coverage rule
(:func:`yoke_core.domain.steering_scope_coverage.live_steering_claims`)
rather than deriving it from the session roster. The roster carries the
same identity on every row as ``steering_group_session_id``, but reaching
it that way costs a complete roster — claims, holdings, liveness,
delivery, presentation — to read one repeated field.

Visibility matches what the roster would have shown, which is deliberately
an OR: a seat is visible when the project it steers is visible, or when the
session holding it lives in a visible project. A session steers a project
it did not start in, and either half alone would drop a real seat.
"""

from __future__ import annotations

from typing import Any, Optional, Set

from yoke_core.domain.steering_scope_coverage import PROJECT_KEY


def _scope_project_id(claim: Any) -> Optional[int]:
    scope = dict(claim.get("scope") or {})
    try:
        return int(scope[PROJECT_KEY])
    except (KeyError, TypeError, ValueError):
        return None


def _home_project_ids(conn: Any, session_ids: tuple[str, ...]) -> dict[str, int]:
    """Home project of each holding session, asked once for all of them."""
    from yoke_core.domain import db_backend

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT session_id, project_id FROM harness_sessions WHERE session_id IN ("
        + ",".join(marker for _ in session_ids)
        + ") AND project_id IS NOT NULL",
        session_ids,
    ).fetchall()
    return {str(dict(row)["session_id"]): int(dict(row)["project_id"]) for row in rows}


def live_steering_group_session_ids(
    conn: Any,
    *,
    visible_project_ids: Optional[Set[int]] = None,
) -> list[str]:
    """Return every live steering seat's session id, sorted.

    ``visible_project_ids`` of ``None`` is the unscoped local call and sees
    every seat. Sorted because the only consumer ranks by sorted id, and a
    stable order keeps that ranking independent of claim age.
    """
    from yoke_core.domain.steering_scope_coverage import live_steering_claims

    claims = live_steering_claims(conn)
    if not claims:
        return []
    if visible_project_ids is None:
        return sorted({str(claim["session_id"]) for claim in claims})
    home_projects = _home_project_ids(
        conn, tuple(dict.fromkeys(str(claim["session_id"]) for claim in claims))
    )
    visible: set[str] = set()
    for claim in claims:
        session_id = str(claim["session_id"])
        steered = _scope_project_id(claim)
        home = home_projects.get(session_id)
        if steered in visible_project_ids or home in visible_project_ids:
            visible.add(session_id)
    return sorted(visible)


__all__ = ["live_steering_group_session_ids"]
