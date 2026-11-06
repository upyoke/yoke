"""Validate owner authority before issuing or consuming an email invite."""

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain import db_backend
from yoke_core.domain.actor_owner_protection import require_owner_change_allowed
from yoke_core.domain.actor_role import require_human_org_role


def require_invite_owner_change(conn, caller, target, org_id, role_id):
    role = "unchanged"
    if role_id is not None:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT name FROM roles WHERE id={p}", (role_id,)
        ).fetchone()
        if row is None:
            raise ValueError(
                "invite_role_missing: choose a seeded human role and invite again"
            )
        role = str(row[0])
        require_human_org_role(role)
    require_owner_change_allowed(conn, caller, target, ("org", org_id), role)
