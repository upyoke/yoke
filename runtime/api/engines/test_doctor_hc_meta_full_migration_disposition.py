"""HC-oneshot-migration-coverage: exception_reason disposition tests.

Sibling test file for the disposition-aware behaviour of drift class
(d). A pre-fix exception-path caller that named the disposition in
``exception_reason`` AND authored the matching decision record under
``docs/archive/decisions/<slug>.md`` satisfies the disposition
requirement and is skipped by the HC.

Co-located with the broader ``test_doctor_hc_meta_full_migration``
suite; kept separate so neither file crosses the authored-file budget.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from yoke_core.engines.doctor import hc_oneshot_migration_coverage

from yoke_core.engines._doctor_hc_meta_full_test_helpers import (
    _NOW_ISO,
    _ensure_migration_audit_table,
    _make_conn,
    _p,
    _result,
    _run_hc,
)


def _with_governance_columns(conn: Any) -> None:
    conn.execute("ALTER TABLE items ADD COLUMN db_mutation_profile TEXT")
    conn.execute(
        "ALTER TABLE items ADD COLUMN db_compatibility_attestation TEXT"
    )


def _insert_audit_row(
    conn: Any,
    *,
    row_id: int,
    name: str,
    backup_path: str,
    exception_reason: str,
) -> None:
    p = _p(conn)
    conn.execute(
        "INSERT INTO migration_audit (id, migration_name, "
        "description, tables_declared, expected_deltas, pre_row_counts, "
        "backup_path, state, started_at, exception_reason) VALUES "
        f"({p}, {p}, '', '[]', '{{}}', '{{}}', {p}, 'completed', {p}, {p})",
        (row_id, name, backup_path, _NOW_ISO, exception_reason),
    )


def test_noncanonical_backup_with_documented_disposition_passes(tmp_path):
    """A non-canonical ``backup_path`` whose ``exception_reason`` names
    an existing ``docs/archive/decisions/<slug>.md`` is treated as
    documented and skipped."""
    decisions = tmp_path / "docs" / "archive" / "decisions"
    decisions.mkdir(parents=True)
    (decisions / "legacy_cutover.md").write_text("# legacy cutover")
    conn = _make_conn()
    _with_governance_columns(conn)
    _ensure_migration_audit_table(conn)
    _insert_audit_row(
        conn,
        row_id=200,
        name="legacy_cutover",
        backup_path=(
            "/tmp/data/yoke.db.legacy_cutover.20260424T153510Z.bak"
        ),
        exception_reason=(
            "pre_merge_breaking cutover routed through exception "
            "pathway. See docs/archive/decisions/legacy_cutover.md."
        ),
    )
    with patch(
        "yoke_core.engines.doctor_report._resolve_repo_root",
        return_value=str(tmp_path),
    ):
        rec = _run_hc(hc_oneshot_migration_coverage, conn)
    result = _result(rec)
    assert result.result == "PASS"


def test_noncanonical_backup_with_missing_record_still_warns(tmp_path):
    """An ``exception_reason`` that names a slug whose decision record
    is NOT on disk does not satisfy the disposition — the row still
    surfaces as WARN."""
    (tmp_path / "docs" / "archive" / "decisions").mkdir(parents=True)
    conn = _make_conn()
    _with_governance_columns(conn)
    _ensure_migration_audit_table(conn)
    _insert_audit_row(
        conn,
        row_id=201,
        name="orphan_cutover",
        backup_path=(
            "/tmp/data/yoke.db.orphan_cutover.20260424T153510Z.bak"
        ),
        exception_reason=(
            "See docs/archive/decisions/orphan_cutover.md."
        ),
    )
    with patch(
        "yoke_core.engines.doctor_report._resolve_repo_root",
        return_value=str(tmp_path),
    ):
        rec = _run_hc(hc_oneshot_migration_coverage, conn)
    result = _result(rec)
    assert result.result == "WARN"
    assert "orphan_cutover" in result.detail


def test_noncanonical_backup_with_empty_exception_reason_still_warns(tmp_path):
    """An empty ``exception_reason`` cannot satisfy the disposition —
    the row remains WARN regardless of which decision records exist."""
    decisions = tmp_path / "docs" / "archive" / "decisions"
    decisions.mkdir(parents=True)
    (decisions / "legacy_cutover.md").write_text("# legacy cutover")
    conn = _make_conn()
    _with_governance_columns(conn)
    _ensure_migration_audit_table(conn)
    _insert_audit_row(
        conn,
        row_id=202,
        name="legacy_cutover",
        backup_path=(
            "/tmp/data/yoke.db.legacy_cutover.20260424T153510Z.bak"
        ),
        exception_reason="",
    )
    with patch(
        "yoke_core.engines.doctor_report._resolve_repo_root",
        return_value=str(tmp_path),
    ):
        rec = _run_hc(hc_oneshot_migration_coverage, conn)
    result = _result(rec)
    assert result.result == "WARN"
    assert "202" in result.detail
