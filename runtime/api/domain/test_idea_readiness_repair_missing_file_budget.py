"""Tests for UNRESOLVED File Budget auto-append at idea status."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional
from unittest import mock

from yoke_core.domain import (
    backlog_queries,
    backlog_rendering,
    backlog_structured_write_op,
    db_backend,
    idea_readiness_repair,
    idea_readiness_repair_missing_file_budget as repair,
)
from yoke_core.domain.file_budget_paths import (
    UNRESOLVED_FILE_BUDGET_MARKER,
    apply_unresolved_file_budget_marker,
    has_unresolved_file_budget,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


_ITEMS_DDL = (
    "CREATE TABLE items (id INTEGER PRIMARY KEY, spec TEXT, design_spec TEXT,"
    " technical_plan TEXT, worktree_plan TEXT, shepherd_log TEXT,"
    " shepherd_caveats TEXT, test_results TEXT, deploy_log TEXT,"
    " db_mutation_profile TEXT,"
    " db_compatibility_attestation TEXT, updated_at TEXT, spec_updated_at TEXT,"
    " spec_updated_by TEXT, status TEXT)"
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_items_schema() -> None:
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _ITEMS_DDL)
        conn.commit()
    finally:
        conn.close()


class _FakeDB:
    def __init__(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._ctx = init_test_db(
            Path(self._tmp_dir.name), apply_schema=_apply_items_schema,
        )
        self.path = self._ctx.__enter__()

    def close(self) -> None:
        try:
            self._ctx.__exit__(None, None, None)
        finally:
            self._tmp_dir.cleanup()

    def insert(self, item_id: int, spec: str, *, status: str = "idea") -> None:
        conn = connect_test_db(self.path)
        try:
            marker = _p(conn)
            conn.execute(
                f"INSERT INTO items (id, spec, status) VALUES "
                f"({marker}, {marker}, {marker})",
                (item_id, spec, status),
            )
            conn.commit()
        finally:
            conn.close()

    def fetch(self, item_id: int) -> Optional[str]:
        conn = connect_test_db(self.path)
        try:
            marker = _p(conn)
            row = conn.execute(
                f"SELECT spec FROM items WHERE id = {marker}", (item_id,),
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None


class _Harness:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._patches = []

    def __enter__(self):
        path = {"return_value": self.db_path}
        self._patches = [
            mock.patch.object(backlog_queries, "_resolve_write_db_path", **path),
            mock.patch.object(backlog_queries, "_assert_write_db_ready"),
            mock.patch.object(
                backlog_structured_write_op, "_resolve_write_db_path", **path,
            ),
            mock.patch.object(
                backlog_structured_write_op, "_assert_write_db_ready",
            ),
            mock.patch.object(backlog_rendering, "_render_body", return_value=True),
            mock.patch.object(
                backlog_rendering, "_sync_body", return_value=(True, "full"),
            ),
            mock.patch.object(backlog_rendering, "_record_sync_failure"),
            mock.patch.object(backlog_rendering, "_maybe_rebuild_board"),
            mock.patch.object(repair, "_emit_audit", return_value=True),
            mock.patch.object(repair, "_rerun_readiness", return_value=("pass", [])),
        ]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        for patch in self._patches:
            patch.stop()


class TestApplyUnresolvedMarker:
    def test_appends_when_section_missing(self):
        updated = apply_unresolved_file_budget_marker("# Spec\n\nBody.\n")
        assert has_unresolved_file_budget(updated) is True
        assert UNRESOLVED_FILE_BUDGET_MARKER in updated

    def test_fills_empty_section(self):
        updated = apply_unresolved_file_budget_marker("## File Budget\n")
        assert has_unresolved_file_budget(updated) is True

    def test_leaves_resolved_budget_alone(self):
        spec = "## File Budget\n\n- `runtime/api/foo.py` — current 10 lines.\n"
        assert apply_unresolved_file_budget_marker(spec) == spec


class TestClassifyMissingFileBudget:
    def test_missing_file_budget_is_recoverable(self):
        assert idea_readiness_repair.classify_readiness_issues(
            [{"code": "MISSING_FILE_BUDGET", "context": {}}],
        ) == idea_readiness_repair.CLASS_MIXED_STALE_COUNT

    def test_missing_plus_unresolved_function_stays_terminal(self):
        assert idea_readiness_repair.classify_readiness_issues([
            {"code": "MISSING_FILE_BUDGET", "context": {}},
            {"code": "UNRESOLVED_FUNCTION", "context": {}},
        ]) == idea_readiness_repair.CLASS_UNRECOVERABLE


class TestAttemptMissingFileBudgetRepair:
    def setup_method(self) -> None:
        self.db = _FakeDB()

    def teardown_method(self) -> None:
        self.db.close()

    def test_appends_marker_at_idea(self):
        item_id = 2215001
        self.db.insert(item_id, "# Spec\n\nRoot cause notes.\n")
        with _Harness(self.db.path):
            outcome = repair.attempt_missing_file_budget_repair(item_id=item_id)
        assert outcome.success, outcome.error
        assert has_unresolved_file_budget(self.db.fetch(item_id) or "") is True

    def test_refuses_outside_idea(self):
        item_id = 2215002
        self.db.insert(item_id, "# Spec\n", status="refining-idea")
        with _Harness(self.db.path):
            outcome = repair.attempt_missing_file_budget_repair(item_id=item_id)
        assert outcome.success is False
        assert outcome.refused_paths[0]["reason"] == "not_idea_status"

    def test_maybe_repair_skips_when_code_absent(self):
        handled, remaining = repair.maybe_repair_missing_file_budget(
            item_id=1, issues=[{"code": "FILE_BUDGET_NOT_IN_CLAIM"}],
        )
        assert handled is None
        assert remaining[0]["code"] == "FILE_BUDGET_NOT_IN_CLAIM"

    def test_maybe_repair_consumes_missing_only(self):
        item_id = 2215003
        self.db.insert(item_id, "# Spec\n")
        with _Harness(self.db.path):
            handled, remaining = repair.maybe_repair_missing_file_budget(
                item_id=item_id,
                issues=[{"code": "MISSING_FILE_BUDGET"}],
            )
        assert handled is not None
        assert handled.success
        assert remaining == []
