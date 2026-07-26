"""Give the runtime narrow ownership authority over registry objects."""

from __future__ import annotations

import hashlib
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.migrations.workflow_registry_runtime_access import (
    _authority_roles,
    _function_owner,
    _relation_owners,
    _sequence_owner,
    invariants as access_invariants,
)
from yoke_core.domain.workflow_schema import (
    WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER,
)

MIGRATION_NAME = "workflow_registry_runtime_ownership_recovery"
_IMMUTABLE_FUNCTION = f"{WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}_fn"
_OWNED_RELATIONS = ("workflows", "workflow_versions")
_OWNER_ROLE_PREFIX = "yoke_workflow_registry_"
_OWNER_ROLE_SUFFIX = "_owner"


def ownership_role_for_database(conn: Any) -> str:
    database = str(conn.execute("SELECT current_database()").fetchone()[0])
    digest = hashlib.sha256(database.encode("utf-8")).hexdigest()[:16]
    return f"{_OWNER_ROLE_PREFIX}{digest}{_OWNER_ROLE_SUFFIX}"


def _role_attributes(conn: Any, role: str) -> tuple[bool, ...] | None:
    row = conn.execute(
        "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
        "rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname = %s",
        (role,),
    ).fetchone()
    if row is None:
        return None
    return tuple(bool(value) for value in row)


def _role_inherits(conn: Any, role: str) -> bool:
    row = conn.execute(
        "SELECT rolinherit FROM pg_roles WHERE rolname = %s",
        (role,),
    ).fetchone()
    return bool(row and row[0])


def _has_role_usage(conn: Any, member: str, role: str) -> bool:
    return bool(
        conn.execute(
            "SELECT pg_has_role(%s, %s, 'USAGE')",
            (member, role),
        ).fetchone()[0]
    )


def _has_schema_privilege(conn: Any, role: str, privilege: str) -> bool:
    return bool(
        conn.execute(
            "SELECT has_schema_privilege(%s, 'public', %s)",
            (role, privilege),
        ).fetchone()[0]
    )


def apply(conn: Any) -> None:
    """Move only registry objects to a no-login role inherited by runtime."""
    if not db_backend.connection_is_postgres(conn):
        return
    access_invariants(conn)
    actor, runtime_owner = _authority_roles(conn)
    if not _role_inherits(conn, runtime_owner):
        raise RuntimeError(
            f"database runtime owner must inherit role privileges: {runtime_owner}"
        )
    owner_role = ownership_role_for_database(conn)
    attributes = _role_attributes(conn, owner_role)

    from psycopg import sql

    if attributes is None:
        conn.execute(
            sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(owner_role))
        )
    elif any(attributes):
        raise RuntimeError(
            f"workflow registry ownership role has unsafe attributes: {owner_role}"
        )
    if not _has_role_usage(conn, actor, owner_role):
        conn.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(owner_role),
                sql.Identifier(actor),
            )
        )
    if not _has_role_usage(conn, runtime_owner, owner_role):
        conn.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(owner_role),
                sql.Identifier(runtime_owner),
            )
        )
    conn.execute(
        sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(
            sql.Identifier(owner_role)
        )
    )

    relation_owners = _relation_owners(conn)
    for relation in _OWNED_RELATIONS:
        current_owner = relation_owners.get(relation)
        if current_owner not in {actor, runtime_owner, owner_role}:
            raise RuntimeError(
                f"workflow registry relation has unexpected owner: "
                f"{relation}:{current_owner}"
            )
        if current_owner == actor:
            conn.execute(
                sql.SQL("ALTER TABLE {} OWNER TO {}").format(
                    sql.Identifier(relation),
                    sql.Identifier(owner_role),
                )
            )

    function_owner = _function_owner(conn)
    if function_owner not in {actor, runtime_owner, owner_role}:
        raise RuntimeError(
            "workflow registry immutable function has unexpected owner: "
            f"{function_owner}"
        )
    if function_owner == actor:
        conn.execute(
            sql.SQL("ALTER FUNCTION {}() OWNER TO {}").format(
                sql.Identifier(_IMMUTABLE_FUNCTION),
                sql.Identifier(owner_role),
            )
        )
    conn.commit()


def invariants(conn: Any) -> None:
    """Require narrow ownership membership and complete runtime authority."""
    if not db_backend.connection_is_postgres(conn):
        return
    access_invariants(conn)
    _, runtime_owner = _authority_roles(conn)
    owner_role = ownership_role_for_database(conn)
    attributes = _role_attributes(conn, owner_role)
    if attributes is None or any(attributes):
        raise AssertionError(
            f"workflow registry ownership role is absent or unsafe: {owner_role}"
        )
    if not _role_inherits(conn, runtime_owner):
        raise AssertionError(
            f"database runtime owner does not inherit role privileges: {runtime_owner}"
        )
    if not _has_role_usage(conn, runtime_owner, owner_role):
        raise AssertionError(
            f"database runtime owner lacks registry ownership role: {runtime_owner}"
        )
    for privilege in ("USAGE", "CREATE"):
        if not _has_schema_privilege(conn, owner_role, privilege):
            raise AssertionError(
                f"workflow registry ownership role lacks public-schema "
                f"{privilege}: {owner_role}"
            )
    accepted_owners = {runtime_owner, owner_role}
    for relation, owner in _relation_owners(conn).items():
        if owner not in accepted_owners:
            raise AssertionError(
                f"workflow registry relation is not runtime-owned: {relation}:{owner}"
            )
    sequence_owner = _sequence_owner(conn)
    if sequence_owner not in accepted_owners:
        raise AssertionError(
            f"workflow registry sequence is not runtime-owned: {sequence_owner}"
        )
    function_owner = _function_owner(conn)
    if function_owner not in accepted_owners:
        raise AssertionError(
            "workflow registry immutable function is not runtime-owned: "
            f"{function_owner}"
        )


__all__ = [
    "MIGRATION_NAME",
    "apply",
    "invariants",
    "ownership_role_for_database",
]
