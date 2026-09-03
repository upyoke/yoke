"""One role check for every action one session takes on another.

Driving somebody else's worker is normal work, and it is normal *with a
role*: authority follows the person, so what a caller may do to a session
is decided by that caller's role on the session's project, never by which
machine either of them runs on. Before this module each session-affecting
handler answered that question for itself — messaging and keep-alive read
one permission inline, termination read a session posture and no role at
all — so the same question had three answers and adding a fourth surface
meant inventing a fifth.

The rule, in one place:

* **message, wake, keep alive, launch** — any member of the target's
  project (the permission its ``operator`` and ``owner`` roles carry).
* **terminate a launched worker** — the same project membership. A worker
  is a command somebody started; whoever may drive it may stop it.
* **terminate another actor's interactive session** — project ``owner``
  or org ``admin``. An operator-opened session is a person sitting at a
  terminal, and ending one out from under them is administration.
* **terminate your own session** — always yours, whatever your role.

A refusal names the actor, the roles it actually holds, and the action it
attempted, because "permission denied" without those three sends the
reader to the wrong place: the usual cause is a real member acting on a
project they were never granted, and only the held-role list shows that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.actor_permissions import (
    PERM_ITEMS_WRITE,
    PERM_PROJECT_ADMIN,
    permission_decision,
)
from yoke_core.domain.session_action_attribution import (
    SESSION_ACTION_LABELS,
    action_label,
)


#: Actions whose target session the payload names outright. Everything
#: else in :data:`SESSION_ACTION_LABELS` resolves its target through an
#: anchor the handler owns (a message audience, a wake's item ref), so
#: the handler applies this same decision per project it resolved.
DIRECTLY_TARGETED_FUNCTIONS = frozenset(
    {
        "session_control.session.wake",
        "session_control.session.terminate",
        "session_control.keepalive.hold",
        "session_control.keepalive.release",
    }
)

TERMINATE_FUNCTION = "session_control.session.terminate"


@dataclass(frozen=True)
class SessionActionDecision:
    """Whether one actor may take one action on one project's session."""

    allowed: bool
    action: str
    project_id: int
    permission_key: str
    message: str = ""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def held_role_names(conn: Any, *, actor_id: int, project_id: int) -> tuple[str, ...]:
    """Return the roles ``actor_id`` holds on the project and on its org."""
    p = _p(conn)
    try:
        rows = conn.execute(
            "SELECT r.name FROM actor_project_roles apr "
            "JOIN roles r ON r.id = apr.role_id "
            f"WHERE apr.actor_id = {p} AND apr.project_id = {p} "
            "UNION "
            "SELECT r.name FROM actor_org_roles aor "
            "JOIN roles r ON r.id = aor.role_id "
            "JOIN projects pj ON pj.org_id = aor.org_id "
            f"WHERE aor.actor_id = {p} AND pj.id = {p}",
            (actor_id, project_id, actor_id, project_id),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 — the listing is advisory detail
            pass
        return ()
    names = {str(row[0]) for row in rows}
    return tuple(sorted(names))


def _refusal(
    *,
    actor_id: int,
    action: str,
    project_id: int,
    permission_key: str,
    roles: tuple[str, ...],
) -> str:
    held = ", ".join(roles) if roles else "no role"
    return (
        f"actor {actor_id} holds {held} on project id {project_id} and may "
        f"not {action} a session there: the action needs "
        f"{permission_key!r}. Recovery: ask a project owner or org admin to "
        f"grant the role that carries it (`python3 -m "
        f"yoke_core.domain.actor_grants_cli grant-project --actor {actor_id} "
        f"--project {project_id} --role owner`), or have an actor who "
        f"already holds it act instead."
    )


def required_permission(
    function_id: str,
    *,
    actor_id: int,
    target: Mapping[str, Any],
    target_is_launched: bool,
) -> str:
    """Return the permission ``function_id`` needs against ``target``.

    Only termination splits: ending another actor's interactive session
    is administration, while ending a launched worker — or your own
    session — is ordinary project work.
    """
    if function_id != TERMINATE_FUNCTION or target_is_launched:
        return PERM_ITEMS_WRITE
    if _same_actor(target.get("actor_id"), actor_id):
        return PERM_ITEMS_WRITE
    return PERM_PROJECT_ADMIN


def _same_actor(target_actor: Any, actor_id: Any) -> bool:
    """True only when both sides name the same numeric actor."""
    try:
        return int(target_actor) == int(actor_id)
    except (TypeError, ValueError):
        return False


def session_is_launched(conn: Any, session_id: str) -> bool:
    """True when a launch started this session rather than a person.

    Both identity columns are read because they are written by different
    events — the relay records the native id, registration records the
    bound session id — and either can be absent on a session that is
    nonetheless a worker.
    """
    p = _p(conn)
    try:
        row = conn.execute(
            "SELECT 1 FROM session_launches "
            f"WHERE registered_session_id = {p} OR native_session_id = {p} "
            "LIMIT 1",
            (session_id, session_id),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 — absence is the safe reading
            pass
        return False
    return row is not None


def authorize_session_action(
    conn: Any,
    *,
    actor_id: int,
    function_id: str,
    project_id: int,
    target: Optional[Mapping[str, Any]] = None,
) -> SessionActionDecision:
    """Decide one session-affecting action against the actor's project role.

    ``target`` is the target session row when one is known; a caller that
    resolved only a project (a message fanned out by anchor) passes none
    and gets the ordinary membership check for that project.
    """
    action = action_label(function_id) or function_id
    row: Mapping[str, Any] = target or {}
    target_session_id = str(row.get("session_id") or "").strip()
    launched = bool(target_session_id) and session_is_launched(conn, target_session_id)
    permission_key = required_permission(
        function_id,
        actor_id=actor_id,
        target=row,
        target_is_launched=launched,
    )
    allowed = permission_decision(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        permission_key=permission_key,
    ).allowed
    if allowed:
        return SessionActionDecision(
            allowed=True,
            action=action,
            project_id=project_id,
            permission_key=permission_key,
        )
    return SessionActionDecision(
        allowed=False,
        action=action,
        project_id=project_id,
        permission_key=permission_key,
        message=_refusal(
            actor_id=actor_id,
            action=action,
            project_id=project_id,
            permission_key=permission_key,
            roles=held_role_names(conn, actor_id=actor_id, project_id=project_id),
        ),
    )


__all__ = [
    "DIRECTLY_TARGETED_FUNCTIONS",
    "SESSION_ACTION_LABELS",
    "SessionActionDecision",
    "authorize_session_action",
    "held_role_names",
    "required_permission",
    "session_is_launched",
]
