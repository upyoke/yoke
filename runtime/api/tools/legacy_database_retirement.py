"""Inspect and retire orphan databases on a connected admin cluster.

Operator tool for databases that are neither registry tenants nor the
declared authoritative install — pre-provisioning residue and stray
rehearsal validation copies. ``inspect`` reports the evidence an operator
needs before authorizing a drop (row counts and newest activity
timestamps); ``drop`` refuses the connected authority database and any
``yoke_tenant_*`` name so the only droppable targets are true orphans.

Runs under a ``*-db-admin`` connected env::

    YOKE_ENV=prod-db-admin python3 -m runtime.api.tools.legacy_database_retirement inspect yoke_prod
    YOKE_ENV=prod-db-admin python3 -m runtime.api.tools.legacy_database_retirement drop yoke_prod
"""

from __future__ import annotations

import argparse
import re
import sys

import psycopg

from yoke_contracts.control_plane_locality import local_authority_exempt

from yoke_core.domain import db_backend

_TENANT_NAME = re.compile(r"^yoke_tenant_\d+$")

_ACTIVITY_PROBES = (
    ("items", "updated_at"),
    ("events", "created_at"),
    ("harness_sessions", "created_at"),
)


def _connect(dbname: str):
    # Cluster-admin maintenance on orphan databases: this tool exists to
    # operate on databases the control plane does not own, under an
    # explicit *-db-admin env selected by the operator.
    with local_authority_exempt():
        return psycopg.connect(
            db_backend.resolve_pg_dsn(dbname), autocommit=True
        )


def _authority_dbname() -> str:
    with local_authority_exempt():
        with psycopg.connect(db_backend.resolve_pg_dsn()) as conn:
            return str(
                conn.execute("SELECT current_database()").fetchone()[0]
            )


def inspect(dbname: str) -> int:
    with _connect(dbname) as conn:
        rows = conn.execute(
            "SELECT relname, n_live_tup FROM pg_stat_user_tables "
            "ORDER BY n_live_tup DESC LIMIT 10"
        ).fetchall()
        print(f"database: {dbname}")
        total = conn.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema='public'"
        ).fetchone()[0]
        print(f"public tables: {total}")
        for name, live in rows:
            print(f"  {name}: ~{live} rows")
        for table, column in _ACTIVITY_PROBES:
            try:
                newest = conn.execute(
                    f'SELECT max("{column}") FROM "{table}"'
                ).fetchone()[0]
            except psycopg.Error:
                newest = "<table absent>"
            print(f"newest {table}.{column}: {newest}")
    return 0


def drop(dbname: str) -> int:
    if _TENANT_NAME.fullmatch(dbname):
        print(f"refusing: {dbname} is a registry tenant name", file=sys.stderr)
        return 2
    authority = _authority_dbname()
    if dbname == authority:
        print(
            f"refusing: {dbname} is the connected authority database",
            file=sys.stderr,
        )
        return 2
    with _connect("postgres") as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (dbname,),
        )
        owner_row = conn.execute(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s",
            (dbname,),
        ).fetchone()
        granted_owner = None
        try:
            conn.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
        except psycopg.errors.InsufficientPrivilege:
            # An RDS admin user may drop only databases whose owner role it
            # holds; borrow the owner role for the drop, then hand it back.
            if owner_row is None:
                raise
            granted_owner = str(owner_row[0])
            conn.execute(f'GRANT "{granted_owner}" TO CURRENT_USER')
            conn.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
        finally:
            if granted_owner is not None:
                conn.execute(f'REVOKE "{granted_owner}" FROM CURRENT_USER')
    print(f"dropped: {dbname} (authority untouched: {authority})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m runtime.api.tools.legacy_database_retirement",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("inspect", "drop"):
        p = sub.add_parser(action)
        p.add_argument("dbname")
    args = parser.parse_args(argv)
    if args.action == "inspect":
        return inspect(args.dbname)
    return drop(args.dbname)


if __name__ == "__main__":
    raise SystemExit(main())
