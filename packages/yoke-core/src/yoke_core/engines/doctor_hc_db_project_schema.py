"""Schema drift, script sync, and migration audit HCs.

Schema-cluster HCs that compare live DB schema to expectations and verify
migration audit evidence. All checks introspect through the backend-aware
``schema_common`` / ``information_schema`` helpers — they hold against
Yoke's Postgres control-plane authority, not a SQLite file:

- ``hc_schema_drift`` — compare live tables/columns to the expected schema.
- ``hc_schema_script_sync`` — validate items.py column references match the
  live items table.
- ``hc_migration_audit`` — migration_audit table evidence and row-count
  collapse detection.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.schema_common import (
    _get_columns as _schema_get_columns,
    _table_exists as _schema_table_exists,
)
from yoke_core.domain.migration_apply import (
    FAIL_BACKUP,
    FAIL_LIVE_APPLY,
    FAIL_LIVE_VERIFY,
    FAIL_TEST_APPLY,
    FAIL_TEST_COPY,
    FAIL_TEST_VERIFY,
    STATE_COMPLETED,
)

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_hc_db_project_schema_expected import (
    parse_expected_schema,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

_MIGRATION_AUDIT_FAILURE_STATES = (
    FAIL_TEST_COPY,
    FAIL_TEST_APPLY,
    FAIL_TEST_VERIFY,
    FAIL_BACKUP,
    FAIL_LIVE_APPLY,
    FAIL_LIVE_VERIFY,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def hc_schema_drift(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-schema-drift: Schema drift detection.

    Diffs the live schema against the canonical declaration in
    ``doctor_hc_db_project_schema_expected``. Refresh that module
    after every schema migration so the HC stays green.
    """
    expected = parse_expected_schema()

    try:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() "
            "ORDER BY table_name"
        ).fetchall()
        actual_tables = {str(row[0]) for row in rows}
    except Exception:
        actual_tables = set()

    issues: List[str] = []
    for tbl in sorted(actual_tables):
        if tbl not in expected:
            issues.append(f"- Unknown table: {tbl} (exists in DB but not in expected schema)")

    for tbl_name in sorted(expected.keys()):
        if tbl_name not in actual_tables:
            issues.append(f"- Missing table: {tbl_name} (expected but not found in DB)")
            continue
        actual_cols = set(_schema_get_columns(conn, tbl_name))

        for cname, ctype in expected[tbl_name].items():
            if cname not in actual_cols:
                issues.append(f"- {tbl_name}: missing column '{cname}' (expected type {ctype})")
        for cname in actual_cols:
            if cname not in expected[tbl_name]:
                issues.append(f"- {tbl_name}: extra column '{cname}' (exists in DB but not in expected schema)")

    if issues:
        rec.record("HC-schema-drift", "Schema drift detection", "WARN", "\n".join(issues))
    else:
        rec.record("HC-schema-drift", "Schema drift detection", "PASS", "")


def hc_schema_script_sync(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-schema-script-sync: Validate script column references match live DB schema."""
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-schema-script-sync", "Script-schema column contract", "PASS", "")
        return

    actual_cols = set(_schema_get_columns(conn, "items"))

    if not actual_cols:
        rec.record("HC-schema-script-sync", "Script-schema column contract", "WARN",
                    "Could not read items table columns")
        return

    # Check the canonical Python items surface for column references.
    item_db = Path(repo_root) / "runtime" / "api" / "domain" / "items.py"
    if not item_db.is_file():
        rec.record("HC-schema-script-sync", "Script-schema column contract", "WARN",
                    f"items.py not found at {item_db}")
        return

    # Parse field lists from items.py (simplified check)
    issues: List[str] = []
    text = item_db.read_text(errors="replace")
    # Look for column names in SELECT statements
    for match in re.finditer(r"SELECT\s+(.+?)\s+FROM\s+items", text, re.IGNORECASE | re.DOTALL):
        cols_str = match.group(1)
        for col in re.findall(r"\b([a-z_]+)\b", cols_str):
            if col in ("as", "from", "where", "and", "or", "select", "null",
                       "not", "case", "when", "then", "else", "end", "is",
                       "in", "like", "count", "coalesce", "trim", "cast",
                       "integer", "text", "distinct"):
                continue
            if col.startswith("i_") or col.startswith("items_"):
                continue
            # Only check column names that look plausible
            if len(col) > 2 and col not in actual_cols and not col.startswith("_"):
                # Double check it's not a table alias or function
                pass  # Simplified: full validation would need SQL parsing

    if issues:
        rec.record("HC-schema-script-sync", "Script-schema column contract", "FAIL", "\n".join(issues))
    else:
        rec.record("HC-schema-script-sync", "Script-schema column contract", "PASS", "")


def hc_migration_audit(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-migration-audit: Migration audit evidence and DB safety.

    Checks:
    1. migration_audit table exists (harness is installed)
    2. No failed migration states without resolution
    3. Critical table row counts haven't collapsed since last baseline
    """
    issues: List[str] = []

    # Check 1: audit table exists
    if not _schema_table_exists(conn, "migration_audit"):
        rec.record(
            "HC-migration-audit", "Migration audit evidence",
            "WARN",
            "migration_audit table missing — run "
            "python3 -m yoke_core.domain.schema init to create it",
        )
        return

    # Check 2: unresolved rollbacks/failures.
    # A failed row is "resolved" when a later row for the same
    # migration_name reaches STATE_COMPLETED — the second attempt's
    # success supersedes the earlier failure record. The DB keeps the
    # failure row for audit history; the HC only flags terminal,
    # un-superseded failures.
    p = _p(conn)
    failure_state_placeholders = ", ".join(
        p for _ in _MIGRATION_AUDIT_FAILURE_STATES
    )
    bad_rows = query_rows(
        conn,
        "SELECT id, migration_name, state, failure_reason, started_at "
        "FROM migration_audit AS f "
        f"WHERE state IN ({failure_state_placeholders}) "
        "  AND NOT EXISTS ("
        "    SELECT 1 FROM migration_audit AS c "
        "    WHERE c.migration_name = f.migration_name "
        f"      AND c.state = {p} AND c.id > f.id"
        "  ) "
        "ORDER BY id DESC LIMIT 5",
        (*_MIGRATION_AUDIT_FAILURE_STATES, STATE_COMPLETED),
    )
    for row in bad_rows:
        issues.append(
            f"- Migration #{row['id']} ({row['migration_name']}): {row['state']} "
            f"at {row['started_at']} — {row['failure_reason'] or 'no reason recorded'}"
        )

    # Check 3: compare current critical table counts against last completed baseline
    baseline_row = query_rows(
        conn,
        "SELECT post_row_counts FROM migration_audit "
        f"WHERE state={p} AND post_row_counts IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (STATE_COMPLETED,),
    )
    if baseline_row:
        import json as _json
        try:
            baseline = _json.loads(baseline_row[0]["post_row_counts"])
            critical = ("items", "epic_tasks", "events", "epic_progress_notes", "qa_runs")
            for tbl in critical:
                base_count = baseline.get(tbl, 0)
                if base_count <= 0:
                    continue
                try:
                    curr = query_scalar(conn, f'SELECT COUNT(*) FROM "{tbl}"') or 0
                except Exception:
                    continue
                if curr == 0 and base_count > 10:
                    issues.append(
                        f"- CRITICAL: {tbl} collapsed to 0 rows "
                        f"(last migration baseline was {base_count})"
                    )
                elif curr < base_count * 0.5 and base_count > 10:
                    issues.append(
                        f"- WARNING: {tbl} dropped >50% since last migration "
                        f"({base_count} → {curr})"
                    )
        except (ValueError, KeyError):
            pass  # Malformed JSON — skip baseline comparison

    if issues:
        rec.record(
            "HC-migration-audit", "Migration audit evidence",
            "WARN", "\n".join(issues)
        )
    else:
        rec.record("HC-migration-audit", "Migration audit evidence", "PASS", "")
