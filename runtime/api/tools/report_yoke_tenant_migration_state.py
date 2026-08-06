"""Report Yoke migration state for every Yoke tenant DB in one environment.

Answers the question a single-database probe cannot: whether the installs
behind one control plane agree about what has been applied to them. Each
tenant is its own database with its own ``applied_migrations`` ledger, so
"the fleet is current" is a claim about every tenant, not about whichever
database a connection happens to resolve to.

Reads only. Credential material is owned by the connection's declared source
and resolved through :func:`db_backend.resolve_pg_dsn`, so no secret reaches
this process's argv or its output.

Usage::

    python3 -m runtime.api.tools.report_yoke_tenant_migration_state <env-name>

where *env-name* is a configured admin connection (for example
``prod-db-admin`` or ``stage-db-admin``).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
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

InvariantCheck = Tuple[str, Optional[Callable[[Any], None]]]

def _connect(dsn: str) -> Any:
    import psycopg

    return psycopg.connect(dsn, connect_timeout=20)


def _org_slugs(cur: Any) -> Optional[List[str]]:
    cur.execute("SELECT to_regclass('organizations')")
    if cur.fetchone()[0] is None:
        return None
    cur.execute("SELECT slug FROM organizations ORDER BY id")
    return [r[0] for r in cur.fetchall()]


def _ledger(cur: Any) -> Optional[List[Tuple[str, str, str, Optional[str]]]]:
    """Return ledger rows, or None when the table does not exist.

    A missing table is not the same as an empty one for a reader, but it is
    the same for the pending-set computation: both make the pending set the
    entire history. It is reported distinctly because the causes differ.
    """
    cur.execute("SELECT to_regclass('applied_migrations')")
    if cur.fetchone()[0] is None:
        return None
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema=current_schema() "
        "AND table_name='applied_migrations' "
        "AND column_name='minimum_serving_version')"
    )
    has_floor = bool(cur.fetchone()[0])
    floor = "minimum_serving_version" if has_floor else "NULL::text"
    cur.execute(
        "SELECT migration_name, applied_at, applied_by, "
        f"{floor} FROM applied_migrations ORDER BY migration_name"
    )
    return list(cur.fetchall())


def _audit_attempts(cur: Any) -> Optional[List[Tuple[str, int, Any]]]:
    """Summarize historical attempts without dumping failure text."""
    cur.execute("SELECT to_regclass('migration_audit')")
    if cur.fetchone()[0] is None:
        return None
    cur.execute(
        "SELECT state, count(*), max(COALESCE(completed_at, started_at)) "
        "FROM migration_audit GROUP BY state ORDER BY state"
    )
    return list(cur.fetchall())


def _latest_audit_outcomes(cur: Any) -> List[Tuple[str, str, Any]]:
    """Return each entry's latest attempt, with id breaking timestamp ties."""
    cur.execute(
        "SELECT DISTINCT ON (migration_name) migration_name, state, "
        "COALESCE(completed_at, started_at) AS observed_at "
        "FROM migration_audit ORDER BY migration_name, observed_at DESC, id DESC"
    )
    return list(cur.fetchall())


def _completed_receipt_names(cur: Any) -> set[str]:
    cur.execute(
        "SELECT DISTINCT migration_name FROM migration_audit "
        "WHERE state='completed'"
    )
    return {str(row[0]) for row in cur.fetchall()}


def _ledger_rows_without_completed_evidence(
    rows: List[Tuple[str, str, str, Optional[str]]], completed: set[str],
) -> List[str]:
    return sorted({str(row[0]) for row in rows} - completed)


def _packaged_invariant_checks() -> List[InvariantCheck]:
    """Load invariant checks from the packaged, ordered Yoke history."""
    from yoke_core.domain import migrations as migration_history_package
    from yoke_core.domain.migration_history import (
        history_dir,
        load_migration_module,
        ordered_entries,
    )

    checks = []
    for entry in ordered_entries(history_dir(migration_history_package)):
        module = load_migration_module(entry.path, entry.name)
        check = getattr(module, "invariants", None)
        checks.append((entry.name, check if callable(check) else None))
    return checks


def _packaged_pending(
    checks: Sequence[InvariantCheck], applied_names: set[str],
) -> List[str]:
    return [name for name, _check in checks if name not in applied_names]


def _applied_invariant_outcomes(
    conn: Any,
    checks: Sequence[InvariantCheck],
    applied_names: set[str],
) -> List[Tuple[str, str, Optional[str]]]:
    """Run applied-entry invariants inside isolated read-only savepoints."""
    outcomes = []
    for name, check in checks:
        if name not in applied_names:
            continue
        if check is None:
            outcomes.append((name, "not_declared", None))
            continue
        conn.execute("SAVEPOINT yoke_report_migration_invariant")
        try:
            check(conn)
        except Exception as exc:  # noqa: BLE001 - report every failed invariant
            conn.execute("ROLLBACK TO SAVEPOINT yoke_report_migration_invariant")
            detail = " ".join(str(exc).split())[:240]
            outcomes.append((name, "failed", f"{type(exc).__name__}: {detail}"))
        else:
            outcomes.append((name, "passed", None))
        finally:
            conn.execute("RELEASE SAVEPOINT yoke_report_migration_invariant")
    return outcomes


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


def _report_database(dsn_for: Any, database: str) -> bool:
    print(f"\n=== {database} ===")
    with _connect(dsn_for(database)) as conn:
        with conn.cursor() as cur:
            orgs = _org_slugs(cur)
            if orgs is None:
                print("  not a Yoke universe (no organizations table)")
                return False
            print(f"  orgs: {orgs}")

            rows = _ledger(cur)
            if rows is None:
                print("  ledger: TABLE ABSENT -> pending set is the whole history")
            elif not rows:
                print("  ledger: empty -> pending set is the whole history")
            else:
                print(f"  ledger: {len(rows)} applied")
                for name, applied_at, applied_by, floor in rows:
                    print(
                        f"    {name} | {applied_at} | {applied_by} | "
                        f"minimum serving {floor or 'none recorded'}"
                    )
                missing_floors = [name for name, _at, _by, floor in rows if not floor]
                print(
                    "  applied rows without a serving floor: "
                    f"{missing_floors or 'none'}"
                )

            applied_names = {str(row[0]) for row in rows or []}
            checks = _packaged_invariant_checks()
            pending = _packaged_pending(checks, applied_names)
            print(f"  packaged migrations pending: {pending or 'none'}")
            outcomes = _applied_invariant_outcomes(conn, checks, applied_names)
            print("  applied migration invariants:")
            for name, state, detail in outcomes:
                suffix = f" ({detail})" if detail else ""
                print(f"    {name}: {state}{suffix}")
            failed_invariants = [
                name for name, state, _detail in outcomes if state != "passed"
            ]

            attempts = _audit_attempts(cur)
            if attempts is None:
                print("  migration audit: TABLE ABSENT")
                missing_receipts = _ledger_rows_without_completed_evidence(
                    rows or [], set(),
                )
            else:
                latest_outcomes = _latest_audit_outcomes(cur)
                unresolved = [
                    (name, state, observed_at)
                    for name, state, observed_at in latest_outcomes
                    if str(state).endswith("_failed")
                ]
                missing_receipts = _ledger_rows_without_completed_evidence(
                    rows or [], _completed_receipt_names(cur),
                )
                print("  migration audit historical attempts:")
                for state, count, latest in attempts:
                    print(f"    {state}: {count} (latest {latest})")
                print(f"  latest unresolved failures: {unresolved or 'none'}")
            print(
                "  ledger rows without completed audit evidence: "
                f"{missing_receipts or 'none'}"
            )

            surviving = _surviving_retired_surfaces(cur)
            print(f"  retired surfaces still present: {surviving or 'none'}")

            if rows is not None and rows and surviving:
                print("  MIXED: ledger claims applied while surfaces survive")
            if (rows is None or not rows) and not surviving:
                print(
                    "  MIXED: surfaces already removed with no ledger record — "
                    "the whole history will re-run on the next converge"
                )
            current = bool(rows) and not pending and not surviving and not failed_invariants
            print(f"  current invariant verdict: {'PASS' if current else 'FAIL'}")
            return current


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] in ([], ["-h"], ["--help"]) or len(args) != 1:
        print(__doc__)
        return 0 if args[:1] in (["-h"], ["--help"]) else 2

    os.environ["YOKE_ENV"] = args[0]
    from yoke_core.domain import db_backend
    from runtime.api.tools.yoke_migration_fleet import tenant_databases

    def dsn_for(database: str) -> str:
        return db_backend.resolve_pg_dsn(dbname=database)

    databases = tenant_databases(dsn_for)
    print(f"environment: {args[0]}")
    print(f"tenant databases: {databases}")
    current = [_report_database(dsn_for, database) for database in databases]
    return 0 if databases and all(current) else 1


if __name__ == "__main__":
    raise SystemExit(main())
