"""Actor authority state and atomic credential retirement."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend


class ActorDisabledError(Exception):
    """An actor may not exercise authority while disabled."""


class ActorStateRefused(Exception):
    """A requested actor state change violates a safety boundary."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def actor_is_active(conn: Any, actor_id: int, *, lock: bool = False) -> bool:
    suffix = " FOR UPDATE" if lock and db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        f"SELECT status FROM actors WHERE id = {_p(conn)}{suffix}", (actor_id,)
    ).fetchone()
    return row is not None and row[0] == "active"


def require_actor_active(conn: Any, actor_id: int, *, lock: bool = False) -> None:
    if not actor_is_active(conn, actor_id, lock=lock):
        raise ActorDisabledError(
            f"actor {actor_id} is disabled or unavailable; ask an org admin "
            "to enable the actor, then sign in again or reconnect its machine"
        )


def set_actor_enabled(
    conn: Any, *, actor_id: int, caller_actor_id: int, enabled: bool, now: str
) -> int:
    """Change actor authority and revoke all live credentials in one transaction.

    Lock the organization and actor before the last-admin check. Credential
    issuance locks the same actor row, so a concurrent mint cannot escape the
    disabling transaction.
    """
    p = _p(conn)
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    try:
        conn.execute(f"SELECT id FROM organizations ORDER BY id{lock}").fetchall()
        row = conn.execute(
            f"SELECT kind, system_component, status FROM actors WHERE id = {p}{lock}",
            (actor_id,),
        ).fetchone()
        if row is None:
            raise ActorStateRefused(f"actor {actor_id} does not exist; refresh Actors")
        kind, component, status = row
        if kind == "system" or component is not None:
            raise ActorStateRefused(
                f"actor {actor_id} is system-critical; choose a human actor instead"
            )
        if not enabled and actor_id == caller_actor_id:
            raise ActorStateRefused(
                "cannot disable your own actor; ask another org admin to do it"
            )
        desired = "active" if enabled else "disabled"
        if status == desired:
            return 0
        if not enabled:
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
                "AND other_actor.status = 'active') "
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
