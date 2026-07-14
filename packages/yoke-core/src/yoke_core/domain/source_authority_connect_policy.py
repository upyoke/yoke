"""Stored policy and PostgreSQL primitives for the source CONNECT fence."""

from __future__ import annotations

import json
from typing import Any

from psycopg import sql


FENCE_POLICY_SCHEMA = "yoke.source-connect-fence/v1"
FENCE_STATE_SCHEMA = "yoke_source_authority"
FENCE_STATE_TABLE = "fence_state"


class SourceConnectFenceError(RuntimeError):
    """The database CONNECT fence could not be established or restored."""


def connect_policy(conn: object) -> dict[str, Any]:
    """Capture physical NULL state and canonical acldefault-expanded CONNECT."""
    row = conn.execute(
        "SELECT d.datname, d.oid, owner.rolname, current_user, "
        "d.datacl IS NULL, d.datacl::text "
        "FROM pg_database d JOIN pg_roles owner ON owner.oid=d.datdba "
        "WHERE d.datname=current_database()"
    ).fetchone()
    entries = [
        {
            "grantee": str(entry[0]), "grantor": str(entry[1]),
            "is_grantable": bool(entry[2]),
        }
        for entry in conn.execute(
            "SELECT CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE grantee.rolname END, "
            "CASE WHEN acl.grantor=0 THEN 'PUBLIC' ELSE grantor.rolname END, "
            "acl.is_grantable "
            "FROM pg_database d CROSS JOIN LATERAL "
            "aclexplode(COALESCE(d.datacl, acldefault('d', d.datdba))) acl "
            "LEFT JOIN pg_roles grantee ON grantee.oid=acl.grantee "
            "LEFT JOIN pg_roles grantor ON grantor.oid=acl.grantor "
            "WHERE d.datname=current_database() AND acl.privilege_type='CONNECT' "
            "ORDER BY 1, 2, 3"
        ).fetchall()
    ]
    return {
        "schema": FENCE_POLICY_SCHEMA,
        "database": str(row[0]), "database_oid": int(row[1]),
        "owner_role": str(row[2]), "admin_role": str(row[3]),
        "datacl_was_null": bool(row[4]),
        "datacl_text": None if row[5] is None else str(row[5]),
        "connect_entries": entries,
    }


def login_role_access(conn: object, *, admin_role: str) -> list[dict[str, Any]]:
    """Enumerate effective CONNECT and owner-membership for every login role."""
    return [
        {
            "role": str(row[0]), "superuser": bool(row[1]),
            "effective_connect": bool(row[2]), "inherits_admin": bool(row[3]),
        }
        for row in conn.execute(
            "SELECT r.rolname, r.rolsuper, "
            "has_database_privilege(r.oid, d.oid, 'CONNECT'), "
            "pg_has_role(r.oid, admin.oid, 'MEMBER') "
            "FROM pg_roles r CROSS JOIN pg_database d "
            "JOIN pg_roles admin ON admin.rolname=%s "
            "WHERE r.rolcanlogin AND d.datname=current_database() "
            "ORDER BY r.rolname",
            (admin_role,),
        ).fetchall()
    ]


def admin_memberships(conn: object) -> list[str]:
    """Return roles whose privileges are effective for the current admin."""
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT r.rolname FROM pg_roles r "
            "WHERE pg_has_role(current_user, r.oid, 'USAGE') ORDER BY r.rolname"
        ).fetchall()
    ]


def fence_state(conn: object) -> dict[str, Any] | None:
    """Read the owner-only durable state without depending on search_path."""
    qualified = f"{FENCE_STATE_SCHEMA}.{FENCE_STATE_TABLE}"
    exists = conn.execute("SELECT to_regclass(%s)", (qualified,)).fetchone()[0]
    if exists is None:
        return None
    row = conn.execute(sql.SQL(
        "SELECT policy, frozen_at, service_stop_receipt FROM {}.{} "
        "WHERE singleton"
    ).format(
        sql.Identifier(FENCE_STATE_SCHEMA), sql.Identifier(FENCE_STATE_TABLE),
    )).fetchone()
    if row is None:
        raise SourceConnectFenceError("durable CONNECT fence state row is missing")
    policy = row[0] if isinstance(row[0], dict) else json.loads(str(row[0]))
    return {
        "policy": policy,
        "frozen_at": str(row[1]),
        "service_stop_receipt": str(row[2]),
    }


def create_fence_state(
    conn: object, *, original: dict[str, Any], frozen_at: str,
    service_stop_receipt: str,
) -> None:
    existing = conn.execute(
        "SELECT owner.rolname FROM pg_namespace n "
        "JOIN pg_roles owner ON owner.oid=n.nspowner WHERE n.nspname=%s",
        (FENCE_STATE_SCHEMA,),
    ).fetchone()
    if existing is not None:
        raise SourceConnectFenceError(
            "source fence control schema already exists without valid state"
        )
    admin_role = str(original["admin_role"])
    conn.execute(sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
        sql.Identifier(FENCE_STATE_SCHEMA), sql.Identifier(admin_role),
    ))
    conn.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(
        sql.Identifier(FENCE_STATE_SCHEMA),
    ))
    conn.execute(sql.SQL(
        "CREATE TABLE {}.{} ("
        "singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton), "
        "policy jsonb NOT NULL, frozen_at text NOT NULL, "
        "service_stop_receipt text NOT NULL)"
    ).format(
        sql.Identifier(FENCE_STATE_SCHEMA), sql.Identifier(FENCE_STATE_TABLE),
    ))
    conn.execute(sql.SQL("REVOKE ALL ON {}.{} FROM PUBLIC").format(
        sql.Identifier(FENCE_STATE_SCHEMA), sql.Identifier(FENCE_STATE_TABLE),
    ))
    conn.execute(sql.SQL(
        "INSERT INTO {}.{} "
        "(singleton, policy, frozen_at, service_stop_receipt) "
        "VALUES (true, %s::jsonb, %s, %s)"
    ).format(
        sql.Identifier(FENCE_STATE_SCHEMA), sql.Identifier(FENCE_STATE_TABLE),
    ), (
        json.dumps(original, sort_keys=True, separators=(",", ":")),
        frozen_at, service_stop_receipt,
    ))


def drop_fence_state(conn: object) -> None:
    conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(
        sql.Identifier(FENCE_STATE_SCHEMA),
    ))


def clear_connect_grants(conn: object, database: str) -> None:
    conn.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
        sql.Identifier(database),
    ))
    roles = conn.execute("SELECT rolname FROM pg_roles ORDER BY rolname").fetchall()
    for role in roles:
        conn.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(
            sql.Identifier(database), sql.Identifier(str(role[0])),
        ))


def grant_connect(
    conn: object, *, database: str, grantee: str, grantable: bool,
) -> None:
    recipient = sql.SQL("PUBLIC") if grantee == "PUBLIC" else sql.Identifier(grantee)
    suffix = sql.SQL(" WITH GRANT OPTION") if grantable else sql.SQL("")
    conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}{}").format(
        sql.Identifier(database), recipient, suffix,
    ))


def decode_policy(raw: Any) -> dict[str, Any]:
    try:
        policy = raw if isinstance(raw, dict) else json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise SourceConnectFenceError("stored CONNECT policy is not valid JSON") from exc
    if not isinstance(policy, dict) or policy.get("schema") != FENCE_POLICY_SCHEMA:
        raise SourceConnectFenceError("stored CONNECT policy schema is unsupported")
    return policy
