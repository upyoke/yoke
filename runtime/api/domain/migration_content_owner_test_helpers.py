"""PostgreSQL role topology for migration-content ownership tests."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
from psycopg import conninfo, sql

from runtime.api.fixtures import pg_testdb


@dataclass(frozen=True)
class AuthorityCase:
    database: str
    maintenance_dsn: str
    tenant_dsn: str
    admin_dsn: str
    tenant_role: str
    admin_role: str
    schema: str


def _role_dsn(database: str, role: str, password: str) -> str:
    base = conninfo.conninfo_to_dict(pg_testdb.dsn_for_test_database(database))
    return conninfo.make_conninfo(
        **{**base, "user": role, "password": password},
    )


@contextmanager
def authority_case():
    """Yield a non-member admin and tenant-owned non-public schema."""
    suffix = uuid.uuid4().hex[:10]
    tenant_role = f"migration_owner_{suffix}"
    admin_role = f"migration_admin_{suffix}"
    schema = f"migration_data_{suffix}"
    password = f"migration-{suffix}-password"
    database = pg_testdb.create_test_database(pooled=False)
    maintenance = pg_testdb.maintenance_dsn()

    with psycopg.connect(maintenance, autocommit=True) as root:
        root.execute(
            sql.SQL("CREATE ROLE {} LOGIN CREATEROLE PASSWORD {}").format(
                sql.Identifier(admin_role), sql.Literal(password)
            )
        )
    admin_maintenance_dsn = conninfo.make_conninfo(
        **{
            **conninfo.conninfo_to_dict(maintenance),
            "user": admin_role,
            "password": password,
        }
    )
    with psycopg.connect(admin_maintenance_dsn, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(tenant_role), sql.Literal(password)
            )
        )
    with psycopg.connect(pg_testdb.dsn_for_test_database(database)) as root:
        database_owner = str(
            root.execute(
                "SELECT pg_get_userbyid(datdba) FROM pg_database "
                "WHERE datname=current_database()"
            ).fetchone()[0]
        )
        root.execute(
            sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                sql.Identifier(schema), sql.Identifier(tenant_role)
            )
        )
        root.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(admin_role)
            )
        )
    assert database_owner != tenant_role

    case = AuthorityCase(
        database=database,
        maintenance_dsn=maintenance,
        tenant_dsn=_role_dsn(database, tenant_role, password),
        admin_dsn=_role_dsn(database, admin_role, password),
        tenant_role=tenant_role,
        admin_role=admin_role,
        schema=schema,
    )
    try:
        yield case
    finally:
        pg_testdb.drop_test_database(database, pooled=False)
        with psycopg.connect(maintenance, autocommit=True) as root:
            root.execute(
                sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(admin_role))
            )
            root.execute(
                sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(tenant_role))
            )


def select_schema(conn: psycopg.Connection, schema: str) -> None:
    """Select the project's non-public schema for one role connection."""
    conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))


__all__ = ["AuthorityCase", "authority_case", "select_schema"]
