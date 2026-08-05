"""Report whether each tenant's workflow rows point at a live current version.

Answers the question a boot failure asks in the negative: the converge refuses
with "workflow <id> has an invalid current version" when
``workflows.current_version_id`` names a ``workflow_versions`` row that is not
there, and the refusal names the workflow but not the id it could not find or
which databases share the condition.

Reads only. Credential material is owned by the connection's declared source
and resolved through :func:`db_backend.resolve_pg_dsn`, so no secret reaches
this process's argv or its output.

Usage::

    python3 -m runtime.api.tools.report_workflow_current_version_integrity <env-name>

where *env-name* is a configured admin connection (for example
``prod-db-admin`` or ``stage-db-admin``).
"""

from __future__ import annotations

import os
import sys
from typing import Any, List, Optional, Tuple

DANGLING_SQL = """
SELECT w.id,
       w.current_version_id,
       (SELECT COUNT(*) FROM workflow_versions v WHERE v.workflow_id = w.id)
FROM workflows w
WHERE w.current_version_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM workflow_versions v WHERE v.id = w.current_version_id
  )
ORDER BY w.id
"""

SURVIVING_SQL = """
SELECT id, version FROM workflow_versions
WHERE workflow_id = %s ORDER BY version
"""


def _connect(dsn: str) -> Any:
    import psycopg

    return psycopg.connect(dsn, connect_timeout=20)


def _tenant_databases(cur: Any) -> List[str]:
    cur.execute(
        "SELECT datname FROM pg_database "
        "WHERE datname LIKE 'yoke_tenant_%' ORDER BY datname"
    )
    return [row[0] for row in cur.fetchall()]


def _report_one(dsn: str, database: str) -> bool:
    """Return True when this database's workflow pointers all resolve."""
    conn = _connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('workflows')")
            if cur.fetchone()[0] is None:
                print(f"  {database}: no workflows table (skipped)")
                return True
            cur.execute(DANGLING_SQL)
            dangling: List[Tuple[Any, ...]] = list(cur.fetchall())
            if not dangling:
                print(f"  {database}: every current_version_id resolves")
                return True
            for workflow_id, current_version_id, version_count in dangling:
                print(
                    f"  {database}: workflow {workflow_id!r} points at "
                    f"version id {current_version_id}, which does not exist "
                    f"({version_count} version row(s) remain)"
                )
                cur.execute(SURVIVING_SQL, (workflow_id,))
                for vid, version in cur.fetchall():
                    print(f"      surviving: id={vid} version={version}")
            return False
    finally:
        conn.close()


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0 if args else 2

    os.environ["YOKE_ENV"] = args[0]
    from yoke_core.domain import db_backend

    print(f"environment: {args[0]}")
    admin = _connect(db_backend.resolve_pg_dsn())
    try:
        admin.autocommit = True
        with admin.cursor() as cur:
            databases = _tenant_databases(cur)
    finally:
        admin.close()

    if not databases:
        print("no tenant databases found")
        return 0

    intact = True
    for database in databases:
        if not _report_one(db_backend.resolve_pg_dsn(dbname=database), database):
            intact = False
    return 0 if intact else 1


if __name__ == "__main__":
    raise SystemExit(main())
