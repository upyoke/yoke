"""Doctor HC tests (Oneshot migration coverage HC).

Other doctor_hc_meta_full tests live in sibling files.

Schema scaffolding shared via _doctor_hc_meta_full_test_helpers (private module).
Uses disposable Postgres test databases and mock subprocess for deterministic testing.
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_oneshot_migration_coverage,
)

from yoke_core.engines._doctor_hc_meta_full_test_helpers import (
    _NOW_ISO,
    _args,
    _ensure_migration_audit_table,
    _completed,
    _iso_days_ago,
    _iso_minutes_ago,
    _make_conn,
    _p,
    _result,
    _results,
    _run_hc,
    _insert_item,
)


class TestOneshotMigrationCoverage:
    """HC-oneshot-migration-coverage: governed DB-mutation authoring drift."""

    @staticmethod
    def _with_governance_columns(conn: Any) -> None:
        conn.execute("ALTER TABLE items ADD COLUMN db_mutation_profile TEXT")
        conn.execute(
            "ALTER TABLE items ADD COLUMN db_compatibility_attestation TEXT"
        )

    def _insert_item(
        self,
        conn: Any,
        *,
        item_id: int,
        status: str = "implementing",
        profile: str = '{"state":"none"}',
        attestation: str = "null",
    ) -> None:
        _insert_item(
            conn,
            item_id,
            "T",
            type="issue",
            status=status,
            created_at=_NOW_ISO,
            updated_at=_NOW_ISO,
            db_mutation_profile=profile,
            db_compatibility_attestation=attestation,
        )

    def test_pass_when_no_drift(self, tmp_path):
        conn = _make_conn()
        self._with_governance_columns(conn)
        # Default-profile items don't trigger; record_audit_fingerprint
        # is resolved against a repo root that has no call sites.
        self._insert_item(conn, item_id=1)
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(tmp_path),
        ):
            rec = _run_hc(hc_oneshot_migration_coverage, conn)
        result = _result(rec)
        assert result.result == "PASS"

    def test_warn_on_malformed_profile(self, tmp_path):
        conn = _make_conn()
        self._with_governance_columns(conn)
        # Apply intent without model_name/migration_modules/etc.
        self._insert_item(
            conn,
            item_id=42,
            profile=json.dumps({"state": "declared", "mutation_intent": "apply"}),
        )
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(tmp_path),
        ):
            rec = _run_hc(hc_oneshot_migration_coverage, conn)
        result = _result(rec)
        assert result.result == "WARN"
        assert "YOK-42" in result.detail
        assert "model_name" in result.detail

    def test_warn_on_pre_merge_safe_without_attestation(self, tmp_path):
        conn = _make_conn()
        self._with_governance_columns(conn)
        self._insert_item(
            conn,
            item_id=77,
            profile=json.dumps(
                {
                    "state": "declared",
                    "model_name": "primary",
                    "mutation_intent": "apply",
                    "migration_modules": ["one"],
                    "compatibility_class": "pre_merge_safe",
                    "migration_strategy": "additive_only",
                    "affected_surfaces": ["events"],
                }
            ),
            attestation="null",
        )
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(tmp_path),
        ):
            rec = _run_hc(hc_oneshot_migration_coverage, conn)
        result = _result(rec)
        assert result.result == "WARN"
        assert "YOK-77" in result.detail
        assert "attestation" in result.detail

    def test_warn_on_missing_decision_record(self, tmp_path):
        # Build a synthetic repo layout with a live call site but no
        # paired decision record.
        repo_root = tmp_path
        api_dir = repo_root / "runtime" / "api" / "domain"
        api_dir.mkdir(parents=True)
        (api_dir / "new_helper.py").write_text(
            textwrap.dedent(
                """\
                from yoke_core.domain.migration_harness import (
                    record_audit_fingerprint,
                )

                def run():
                    record_audit_fingerprint(
                        db_path="x",
                        name="novel-exception",
                        description="",
                        tables=[],
                        pre_counts={},
                        post_counts={},
                        exception_reason="bounded no-backup exception",
                    )
                """
            )
        )
        # No docs/archive/decisions/novel-exception.md → HC must flag it.
        (repo_root / "docs" / "archive" / "decisions").mkdir(parents=True)

        conn = _make_conn()
        self._with_governance_columns(conn)
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(repo_root),
        ):
            rec = _run_hc(hc_oneshot_migration_coverage, conn)
        result = _result(rec)
        assert result.result == "WARN"
        assert "novel-exception" in result.detail
        assert "decision record" in result.detail

    def test_pass_when_decision_record_paired(self, tmp_path):
        repo_root = tmp_path
        api_dir = repo_root / "runtime" / "api" / "domain"
        api_dir.mkdir(parents=True)
        (api_dir / "paired_helper.py").write_text(
            textwrap.dedent(
                """\
                from yoke_core.domain.migration_harness import (
                    record_audit_fingerprint,
                )

                def run():
                    record_audit_fingerprint(
                        db_path="x",
                        name="events-prune",
                        description="",
                        tables=[],
                        pre_counts={},
                        post_counts={},
                        exception_reason="bounded no-backup exception",
                    )
                """
            )
        )
        decisions = repo_root / "docs" / "archive" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / "events-prune.md").write_text("# paired")

        conn = _make_conn()
        self._with_governance_columns(conn)
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(repo_root),
        ):
            rec = _run_hc(hc_oneshot_migration_coverage, conn)
        result = _result(rec)
        assert result.result == "PASS"

    def test_terminal_items_skipped(self, tmp_path):
        conn = _make_conn()
        self._with_governance_columns(conn)
        # A done item with a malformed profile should be ignored.
        self._insert_item(
            conn,
            item_id=10,
            status="done",
            profile=json.dumps({"state": "declared", "mutation_intent": "apply"}),
        )
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(tmp_path),
        ):
            rec = _run_hc(hc_oneshot_migration_coverage, conn)
        result = _result(rec)
        assert result.result == "PASS"

    def _insert_audit_row(
        self,
        conn: Any,
        *,
        row_id: int,
        name: str,
        backup_path: str,
        exception_reason: str = "",
    ) -> None:
        p = _p(conn)
        conn.execute(
            "INSERT INTO migration_audit (id, migration_name, "
            "description, tables_declared, expected_deltas, pre_row_counts, "
            "backup_path, state, started_at, exception_reason) VALUES "
            f"({p}, {p}, '', '[]', '{{}}', '{{}}', {p}, 'completed', {p}, {p})",
            (row_id, name, backup_path, _NOW_ISO, exception_reason),
        )

    def test_warn_on_noncanonical_audit_backup_path(self, tmp_path):
        """Drift class (d): audit rows whose ``backup_path`` is populated
        but does not match the canonical ``backups/<stem>.<ts>.<reason>.sqlite3``
        shape are surfaced for operator disposition."""
        conn = _make_conn()
        self._with_governance_columns(conn)
        _ensure_migration_audit_table(conn)
        self._insert_audit_row(
            conn,
            row_id=99,
            name="legacy_cutover",
            backup_path=(
                "/tmp/data/yoke.db.legacy_cutover.20260424T153510Z.bak"
            ),
        )
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(tmp_path),
        ):
            rec = _run_hc(hc_oneshot_migration_coverage, conn)
        result = _result(rec)
        assert result.result == "WARN"
        assert "99" in result.detail
        assert "legacy_cutover" in result.detail
        assert "non-canonical" in result.detail

    def test_canonical_audit_backup_path_does_not_warn(self, tmp_path):
        """A row pointing at a canonical ``.yoke/backups/*.sql`` file
        (the shape the Postgres backup substrate emits) must NOT be
        surfaced as drift."""
        conn = _make_conn()
        self._with_governance_columns(conn)
        _ensure_migration_audit_table(conn)
        self._insert_audit_row(
            conn,
            row_id=101,
            name="canonical_cutover",
            backup_path=(
                "/tmp/.yoke/backups/postgres.20260424-031441."
                "pre-migration-canonical_cutover.sql"
            ),
        )
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(tmp_path),
        ):
            rec = _run_hc(hc_oneshot_migration_coverage, conn)
        result = _result(rec)
        assert result.result == "PASS"

    def test_empty_audit_backup_path_does_not_warn(self, tmp_path):
        """Drift class (d) ignores rows whose ``backup_path`` is empty —
        that is the explicit no-backup branch used by retention-style
        exception-path callers."""
        conn = _make_conn()
        self._with_governance_columns(conn)
        _ensure_migration_audit_table(conn)
        self._insert_audit_row(
            conn,
            row_id=102,
            name="events-prune",
            backup_path="",
        )
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(tmp_path),
        ):
            rec = _run_hc(hc_oneshot_migration_coverage, conn)
        result = _result(rec)
        assert result.result == "PASS"
