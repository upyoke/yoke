"""Report migration state for every tenant database in one environment.

Answers the question a single-database probe cannot: whether the installs
behind one control plane agree about what has been applied to them. Each
tenant is its own database with its own ``applied_migrations`` ledger, so
"the fleet is current" is a claim about every tenant, not about whichever
database a connection happens to resolve to.

Reads only. Credential material is owned by the connection's declared source
and resolved through :func:`db_backend.resolve_pg_dsn`, so no secret reaches
this process's argv or its output.

Usage::

    python3 -m runtime.api.tools.report_fleet_migration_state <env-name>

where *env-name* is a configured admin connection (for example
``prod-db-admin`` or ``stage-db-admin``).
"""

from __future__ import annotations

import os
import sys
from typing import Any, List, Optional, Tuple

#: Surfaces the superseded-column entry removes. Presence means that entry's
#: effect has not reached the database, whatever its ledger claims.
RETIRED_SURFACES: Tuple[Tuple[str, str], ...] = (
    ("items", "flow"),
    ("items", "type"),
    ("items", "worktree"),
    ("items", "browser_qa_metadata"),
    ("path_claims", "item_id"),
    ("path_claims", "session_id"),
    ("path_claims", "work_claim_id"),
    ("path_claims", "actor_id"),
    ("events", "parent_id"),
    ("events", "user_id"),
)

def _connect(dsn: str) -> Any:
    import psycopg

    return psycopg.connect(dsn, connect_timeout=20)


def _org_slugs(cur: Any) -> Optional[List[str]]:
    cur.execute("SELECT to_regclass('organizations')")
    if cur.fetchone()[0] is None:
        return None
    cur.execute("SELECT slug FROM organizations ORDER BY id")
    return [r[0] for r in cur.fetchall()]


def _ledger(cur: Any) -> Optional[List[Tuple[str, str, str]]]:
    """Return ledger rows, or None when the table does not exist.

    A missing table is not the same as an empty one for a reader, but it is
    the same for the pending-set computation: both make the pending set the
    entire history. It is reported distinctly because the causes differ.
    """
    cur.execute("SELECT to_regclass('applied_migrations')")
    if cur.fetchone()[0] is None:
        return None
    cur.execute(
        "SELECT migration_name, applied_at, applied_by "
        "FROM applied_migrations ORDER BY migration_name"
    )
    return list(cur.fetchall())


def _surviving_retired_surfaces(cur: Any) -> List[str]:
    surviving = []
    for table, column in RETIRED_SURFACES:
        cur.execute(
            "SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
            "WHERE c.relname = %s AND a.attname = %s "
            "AND a.attnum > 0 AND NOT a.attisdropped",
            (table, column),
        )
        if cur.fetchone():
            surviving.append(f"{table}.{column}")
    return surviving


def _report_database(dsn_for: Any, database: str) -> None:
    print(f"\n=== {database} ===")
    with _connect(dsn_for(database)) as conn:
        with conn.cursor() as cur:
            orgs = _org_slugs(cur)
            if orgs is None:
                print("  not a Yoke universe (no organizations table)")
                return
            print(f"  orgs: {orgs}")

            rows = _ledger(cur)
            if rows is None:
                print("  ledger: TABLE ABSENT -> pending set is the whole history")
            elif not rows:
                print("  ledger: empty -> pending set is the whole history")
            else:
                print(f"  ledger: {len(rows)} applied")
                for name, applied_at, applied_by in rows:
                    print(f"    {name} | {applied_at} | {applied_by}")

            surviving = _surviving_retired_surfaces(cur)
            print(f"  retired surfaces still present: {surviving or 'none'}")

            if rows is not None and rows and surviving:
                print("  MIXED: ledger claims applied while surfaces survive")
            if (rows is None or not rows) and not surviving:
                print(
                    "  MIXED: surfaces already removed with no ledger record — "
                    "the whole history will re-run on the next converge"
                )


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(__doc__)
        return 2

    os.environ["YOKE_ENV"] = args[0]
    from yoke_core.domain import db_backend
    from yoke_core.domain.migration_fleet_preflight import tenant_databases

    def dsn_for(database: str) -> str:
        return db_backend.resolve_pg_dsn(dbname=database)

    databases = tenant_databases(dsn_for)
    print(f"environment: {args[0]}")
    print(f"tenant databases: {databases}")
    for database in databases:
        _report_database(dsn_for, database)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
