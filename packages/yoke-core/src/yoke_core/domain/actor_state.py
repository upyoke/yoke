"""Actor authority state and atomic credential retirement."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.actors import SYSTEM_COMPONENT_YOKE_CORE


class ActorDisabledError(Exception):
    """An actor may not exercise authority while disabled."""


class ActorStateRefused(Exception):
    """A requested actor state change violates a safety boundary."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def actor_status_sql(conn: Any, alias: str) -> str:
    """Read status before and after the additive column reaches a universe.

    The workstation can drive the serving API's own release before boot
    convergence. An absent column means the legacy schema, whose actors all
    had authority; an existing column with NULL or an unknown value does not.
    """
    if not db_backend.connection_is_postgres(conn):
        return f"{alias}.status"
    actor = f"to_jsonb({alias})"
    return (
        f"CASE WHEN jsonb_exists({actor}, 'status') "
        f"THEN {actor}->>'status' ELSE 'active' END"
    )


def actor_active_sql(conn: Any, alias: str) -> str:
    return f"({actor_status_sql(conn, alias)}) = 'active'"


def actor_is_active(conn: Any, actor_id: int, *, lock: bool = False) -> bool:
    suffix = " FOR UPDATE" if lock and db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        f"SELECT {actor_active_sql(conn, 'a')} FROM actors a "
        f"WHERE a.id = {_p(conn)}{suffix}",
        (actor_id,),
    ).fetchone()
    return row is not None and bool(row[0])


def require_actor_active(conn: Any, actor_id: int, *, lock: bool = False) -> None:
    if not actor_is_active(conn, actor_id, lock=lock):
        raise ActorDisabledError(
            f"actor {actor_id} is disabled or unavailable; ask an org admin "
            "to enable the actor, then sign in again or reconnect its machine"
        )


def has_active_deployment_credential(conn: Any, actor_id: int) -> bool:
    """A serving deployment actor must retire its bearer before disable."""
    from yoke_core.domain.actor_permissions import ROLE_DEPLOYMENT_CI

    p = _p(conn)
    row = conn.execute(
        "SELECT 1 FROM actor_project_roles apr "
        "JOIN roles r ON r.id = apr.role_id "
        "JOIN api_tokens t ON t.actor_id = apr.actor_id AND t.status = 'active' "
        f"WHERE apr.actor_id = {p} AND r.name = {p} LIMIT 1",
        (actor_id, ROLE_DEPLOYMENT_CI),
    ).fetchone()
    return row is not None


def set_actor_enabled(
    conn: Any,
    *,
    actor_id: int,
    caller_actor_id: int,
    enabled: bool,
    now: str,
    confirm_system_retirement: bool = False,
) -> int:
    """Change actor authority and revoke all live credentials in one transaction.

    Lock the organization and actor before the last-admin check. Credential
    issuance locks the same actor row, so a concurrent mint cannot escape the
    disabling transaction.
    """
    p = _p(conn)
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    status_present = (
        "jsonb_exists(to_jsonb(a), 'status')"
        if db_backend.connection_is_postgres(conn)
        else "1"
    )
    try:
        conn.execute(f"SELECT id FROM organizations ORDER BY id{lock}").fetchall()
        row = conn.execute(
            f"SELECT a.kind, a.system_component, {status_present}, "
            f"{actor_status_sql(conn, 'a')} FROM actors a WHERE a.id = {p}{lock}",
            (actor_id,),
        ).fetchone()
        if row is None:
            raise ActorStateRefused(f"actor {actor_id} does not exist; refresh Actors")
        kind, component, has_status, status = row
        if not has_status:
            raise ActorStateRefused(
                "actor enable/disable requires the serving build to boot-converge "
                "the actor status column; deploy that build first"
            )
        if not enabled and actor_id == caller_actor_id:
            raise ActorStateRefused(
                "cannot disable your own actor; ask another org admin to do it"
            )
        desired = "active" if enabled else "disabled"
        if status == desired:
            return 0
        if not enabled:
            if kind == "system" or component is not None:
                if component == SYSTEM_COMPONENT_YOKE_CORE:
                    raise ActorStateRefused(
                        "the canonical core actor cannot be disabled; choose "
                        "a different actor"
                    )
                if has_active_deployment_credential(conn, actor_id):
                    raise ActorStateRefused(
                        f"actor {actor_id} has an active deployment credential; "
                        "retire its release dependency and revoke that "
                        "credential before disabling it"
                    )
                if not confirm_system_retirement:
                    raise ActorStateRefused(
                        f"actor {actor_id} is a system actor; inspect its live "
                        "workflow and service references, then retry with "
                        "--confirm-system-retirement"
                    )
            active_admin = actor_active_sql(conn, "other_actor")
            last_admin = conn.execute(
                "SELECT aor.org_id FROM actor_org_roles aor "
                "JOIN roles r ON r.id = aor.role_id "
                f"WHERE aor.actor_id = {p} AND r.name = 'admin' "
                "AND NOT EXISTS ("
                "SELECT 1 FROM actor_org_roles other "
                "JOIN roles other_role ON other_role.id = other.role_id "
                "JOIN actors other_actor ON other_actor.id = other.actor_id "
                "WHERE other.org_id = aor.org_id AND other.actor_id <> aor.actor_id "
                "AND other_role.name = 'admin' AND other_actor.kind = 'human' "
                f"AND {active_admin}) "
                "LIMIT 1",
                (actor_id,),
            ).fetchone()
            if last_admin is not None:
                raise ActorStateRefused(
                    f"actor {actor_id} is the last active admin of org "
                    f"{last_admin[0]}; grant another active human the admin role first"
                )
        conn.execute(
            f"UPDATE actors SET status = {p} WHERE id = {p}",
            (desired, actor_id),
        )
        revoked = 0
        if not enabled:
            conn.execute(
                f"UPDATE web_sessions SET revoked_at = {p} "
                f"WHERE actor_id = {p} AND revoked_at IS NULL",
                (now, actor_id),
            )
            token_rows = conn.execute(
                f"SELECT id FROM api_tokens WHERE actor_id = {p} AND status = 'active'",
                (actor_id,),
            ).fetchall()
            for (token_id,) in token_rows:
                conn.execute(
                    f"UPDATE api_tokens SET status = 'revoked', revoked_at = {p} "
                    f"WHERE id = {p}",
                    (now, token_id),
                )
                conn.execute(
                    "INSERT INTO api_token_audit "
                    "(api_token_id, actor_id, event_type, outcome, created_at) "
                    f"VALUES ({p}, {p}, {p}, {p}, {p})",
                    (token_id, actor_id, "revoked", "actor_disabled", now),
                )
                revoked += 1
        conn.commit()
        return revoked
    except Exception:
        conn.rollback()
        raise
