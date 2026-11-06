"""Protect owner grants and serialize changes that could remove the last owner."""

from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain import db_backend
from yoke_core.domain.actor_state import actor_active_sql


def _owners(conn: Any, kind: str, scope_id: int, *, active: bool = True) -> set[int]:
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        f"SELECT a.id FROM actor_{kind}_roles ar "
        "JOIN roles r ON r.id = ar.role_id JOIN actors a ON a.id = ar.actor_id "
        f"WHERE ar.{kind}_id = {p} AND r.name = 'owner' "
        "AND a.kind = 'human' "
        + (f"AND {actor_active_sql(conn, 'a')}" if active else ""),
        (scope_id,),
    ).fetchall()
    return {int(row[0]) for row in rows}


def require_owner_change_allowed(
    conn: Any,
    caller: int | None,
    target: int,
    scope: tuple[str, int],
    new_role: str | None,
) -> None:
    """Require an active owner for any owner edit, then preserve a last owner.

    Organization rows serialize org and project changes with actor disabling.
    A project owner can be managed by an owner of the project or its org.
    This function never commits or rolls back the caller's transaction.
    """
    from yoke_core.domain.actor_role import ActorRoleRefused

    kind, scope_id = scope
    if kind not in ("org", "project"):
        raise ValueError("owner scope must be org or project")
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    conn.execute(f"SELECT id FROM organizations ORDER BY id{lock}").fetchall()
    owners = _owners(conn, kind, scope_id)
    governing_owners = set(owners)
    if kind == "project":
        org = conn.execute(
            f"SELECT org_id FROM projects WHERE id = {p}", (scope_id,)
        ).fetchone()
        if org and org[0] is not None:
            governing_owners |= _owners(conn, "org", int(org[0]))
    target_owner = target in _owners(conn, kind, scope_id, active=False)
    if kind == "project" and org and org[0] is not None:
        target_owner |= target in _owners(conn, "org", int(org[0]), active=False)
    if (target_owner or new_role == "owner") and caller not in governing_owners:
        raise ActorRoleRefused(
            "owner_protected",
            compose_refusal(
                "owner_protected: only an active human owner may grant owner or edit an owner",
                recovery="Ask an owner of this scope to make the change",
            ),
        )
    if (
        target in owners
        and new_role not in ("owner", "unchanged")
        and not (governing_owners - {target})
    ):
        raise ActorRoleRefused(
            "last_owner",
            compose_refusal(
                "last_owner: this change would remove the last active human owner",
                recovery="Grant owner to another active person first",
            ),
        )


def seed_bootstrap_owner(conn: Any, actor_id: int, org_id: int) -> None:
    """Seed the first owner only in a universe with exactly one active person.

    Local birth and explicit token bootstrap own this initial authority; normal
    grants cannot invoke this escape from the requirement for an existing owner.
    An established owner re-entering bootstrap keeps their role.
    """
    from yoke_core.domain.actors import sole_human_actor_id
    from yoke_core.domain.actor_role import ActorRoleRefused
    from yoke_core.domain.db_helpers import instant_parameter
    from yoke_contracts.timestamps import utc_now

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    conn.execute(f"SELECT id FROM organizations ORDER BY id{lock}").fetchall()
    owners = _owners(conn, "org", org_id)
    if actor_id in owners:
        require_owner_change_allowed(conn, actor_id, actor_id, ("org", org_id), "owner")
        return
    if owners or sole_human_actor_id(conn) != actor_id:
        raise ActorRoleRefused(
            "owner_protected",
            compose_refusal(
                "owner_protected: initial owner bootstrap requires the sole active person",
                recovery="Ask an existing owner to grant owner to this person",
            ),
        )
    conn.execute(
        f"DELETE FROM actor_org_roles WHERE actor_id={p} AND org_id={p}",
        (actor_id, org_id),
    )
    conn.execute(
        "INSERT INTO actor_org_roles "
        "(actor_id,org_id,role_id,granted_at,granted_by_actor_id) "
        f"SELECT {p},{p},id,{p},{p} FROM roles WHERE name='owner'",
        (actor_id, org_id, instant_parameter(conn, utc_now()), actor_id),
    )
    require_owner_change_allowed(conn, actor_id, actor_id, ("org", org_id), "owner")
