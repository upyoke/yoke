"""Grant the database runtime owner access to admin-created registry objects."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists

MIGRATION_NAME = "workflow_registry_runtime_access"
_REGISTRY_TABLES = ("workflows", "workflow_versions")
_REGISTRY_SEQUENCE = "workflow_versions_id_seq"
_IMMUTABLE_FUNCTION = "workflow_versions_immutable_fn"


def _authority_roles(conn: Any) -> tuple[str, str]:
    row = conn.execute(
        "SELECT current_user, pg_get_userbyid(datdba) "
        "FROM pg_database WHERE datname = current_database()"
    ).fetchone()
    if row is None:
        raise RuntimeError("current database ownership is unavailable")
    return str(row[0]), str(row[1])


def _relation_owners(conn: Any) -> dict[str, str]:
    rows = conn.execute(
        "SELECT c.relname, pg_get_userbyid(c.relowner) "
        "FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' "
        "AND c.relname IN ('workflows', 'workflow_versions') "
        "ORDER BY c.relname"
    ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _function_owner(conn: Any) -> str | None:
    row = conn.execute(
        "SELECT pg_get_userbyid(p.proowner) "
        "FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' "
        "AND p.proname = 'workflow_versions_immutable_fn'"
    ).fetchone()
    return None if row is None else str(row[0])


def _sequence_owner(conn: Any) -> str | None:
    row = conn.execute(
        "SELECT pg_get_userbyid(c.relowner) "
        "FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' "
        "AND c.relname = 'workflow_versions_id_seq' "
        "AND c.relkind = 'S'"
    ).fetchone()
    return None if row is None else str(row[0])


def apply(conn: Any) -> None:
    """Grant full registry use while leaving existing ownership intact."""
    if not db_backend.connection_is_postgres(conn):
        return
    if not all(_table_exists(conn, table) for table in _REGISTRY_TABLES):
        raise RuntimeError("workflow registry tables must exist before access repair")

    actor, runtime_owner = _authority_roles(conn)
    relation_owners = _relation_owners(conn)
    function_owner = _function_owner(conn)
    sequence_owner = _sequence_owner(conn)
    object_owners = set(relation_owners.values())
    if function_owner is not None:
        object_owners.add(function_owner)
    if sequence_owner is not None:
        object_owners.add(sequence_owner)
    unexpected = object_owners - {actor, runtime_owner}
    if unexpected:
        raise RuntimeError(
            "workflow registry objects have unexpected owners: "
            + ", ".join(sorted(unexpected))
        )
    from psycopg import sql

    for table in _REGISTRY_TABLES:
        if relation_owners.get(table) == actor:
            conn.execute(
                sql.SQL(
                    "GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, "
                    "REFERENCES, TRIGGER ON TABLE {} TO {}"
                ).format(
                    sql.Identifier(table),
                    sql.Identifier(runtime_owner),
                )
            )
    if sequence_owner == actor:
        conn.execute(
            sql.SQL("GRANT USAGE, SELECT, UPDATE ON SEQUENCE {} TO {}").format(
                sql.Identifier(_REGISTRY_SEQUENCE),
                sql.Identifier(runtime_owner),
            )
        )
    if function_owner == actor:
        conn.execute(
            sql.SQL("GRANT EXECUTE ON FUNCTION {}() TO {}").format(
                sql.Identifier(_IMMUTABLE_FUNCTION),
                sql.Identifier(runtime_owner),
            )
        )
    conn.commit()


def invariants(conn: Any) -> None:
    """Require the database owner to have complete registry access."""
    if not db_backend.connection_is_postgres(conn):
        return
    _, runtime_owner = _authority_roles(conn)
    owners = _relation_owners(conn)
    missing = set(_REGISTRY_TABLES) - set(owners)
    if missing:
        raise AssertionError(
            "workflow registry tables are missing: " + ", ".join(sorted(missing))
        )
    table_privileges = (
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "TRUNCATE",
        "REFERENCES",
        "TRIGGER",
    )
    denied = []
    for table in _REGISTRY_TABLES:
        for privilege in table_privileges:
            allowed = conn.execute(
                "SELECT has_table_privilege(%s, %s, %s)",
                (runtime_owner, table, privilege),
            ).fetchone()[0]
            if not allowed:
                denied.append(f"{table}:{privilege}")
    if _sequence_owner(conn) is not None:
        for privilege in ("USAGE", "SELECT", "UPDATE"):
            allowed = conn.execute(
                "SELECT has_sequence_privilege(%s, %s, %s)",
                (runtime_owner, _REGISTRY_SEQUENCE, privilege),
            ).fetchone()[0]
            if not allowed:
                denied.append(f"{_REGISTRY_SEQUENCE}:{privilege}")
    if _function_owner(conn) is not None:
        allowed = conn.execute(
            "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
            (runtime_owner, f"{_IMMUTABLE_FUNCTION}()"),
        ).fetchone()[0]
        if not allowed:
            denied.append(f"{_IMMUTABLE_FUNCTION}:EXECUTE")
    if denied:
        raise AssertionError(
            f"workflow registry access is incomplete for {runtime_owner}: "
            + ", ".join(denied)
        )


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
