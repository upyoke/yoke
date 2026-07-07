"""Tests for yoke_core.domain.idea_readiness_repair."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock

from yoke_core.domain import (
    backlog_queries,
    backlog_rendering,
    backlog_structured_write_op,
    db_backend,
    idea_readiness_repair,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


_SAMPLE_PATH = "runtime/api/test_idea_readiness_check_path_extraction.py"
_OTHER_PATH = "runtime/api/domain/idea_readiness_check.py"

# Minimal ``items`` schema the structured-write path touches, applied through the
# backend factory so the seed shares the DB the code-under-test reads.
_ITEMS_DDL = (
    "CREATE TABLE items (id INTEGER PRIMARY KEY, spec TEXT, design_spec TEXT,"
    " technical_plan TEXT, worktree_plan TEXT, shepherd_log TEXT,"
    " shepherd_caveats TEXT, test_results TEXT, deploy_log TEXT,"
    " browser_qa_metadata TEXT, db_mutation_profile TEXT,"
    " db_compatibility_attestation TEXT, updated_at TEXT, spec_updated_at TEXT,"
    " spec_updated_by TEXT)"
)


def _spec(*entries) -> str:
    body = ["# Spec\n\n## File Budget\n"]
    for path, recorded in entries:
        body.append(f"- `{path}` = {recorded}\n")
    return "".join(body)


def _stale_issue(path: str, recorded: int, actual: int = 0) -> dict:
    return {"code": "STALE_LINE_COUNT",
            "context": {"path": path, "recorded": recorded, "actual": actual}}


class TestClassifyReadinessIssues(unittest.TestCase):
    def test_empty_is_pass(self):
        self.assertEqual(
            idea_readiness_repair.classify_readiness_issues([]),
            idea_readiness_repair.CLASS_PASS,
        )

    def test_pure_stale_count(self):
        self.assertEqual(
            idea_readiness_repair.classify_readiness_issues(
                [_stale_issue("x", 1)],
            ),
            idea_readiness_repair.CLASS_PURE_STALE_COUNT,
        )

    def test_stale_plus_recoverable_claim_is_mixed(self):
        issues = [
            _stale_issue("a", 1),
            {"code": "FILE_BUDGET_NOT_IN_CLAIM", "context": {"path": "b"}},
        ]
        self.assertEqual(
            idea_readiness_repair.classify_readiness_issues(issues),
            idea_readiness_repair.CLASS_MIXED_STALE_COUNT,
        )

    def test_unresolved_function_is_unrecoverable(self):
        issues = [_stale_issue("a", 1),
                  {"code": "UNRESOLVED_FUNCTION", "context": {}}]
        self.assertEqual(
            idea_readiness_repair.classify_readiness_issues(issues),
            idea_readiness_repair.CLASS_UNRECOVERABLE,
        )

    def test_missing_sibling_alone_is_unrecoverable(self):
        issues = [{"code": "MISSING_SIBLING_PLAN", "context": {"path": "x"}}]
        self.assertEqual(
            idea_readiness_repair.classify_readiness_issues(issues),
            idea_readiness_repair.CLASS_UNRECOVERABLE,
        )


class TestApplyReplacements(unittest.TestCase):
    def test_single_match_replaced(self):
        spec = "- `foo.py` = 100\n"
        text, refused = idea_readiness_repair.apply_stale_count_replacements(
            spec, [idea_readiness_repair.RepairedPath("foo.py", 100, 155)],
        )
        self.assertEqual(text, "- `foo.py` = 155\n")
        self.assertEqual(refused, [])

    def test_missing_entry_refused(self):
        text, refused = idea_readiness_repair.apply_stale_count_replacements(
            "- `bar.py` = 100\n",
            [idea_readiness_repair.RepairedPath("foo.py", 100, 155)],
        )
        self.assertEqual(text, "- `bar.py` = 100\n")
        self.assertEqual(refused[0]["reason"], "missing_file_budget_entry")

    def test_duplicate_match_refused(self):
        spec = "- `foo.py` = 100\nlater: `foo.py` = 200\n"
        text, refused = idea_readiness_repair.apply_stale_count_replacements(
            spec, [idea_readiness_repair.RepairedPath("foo.py", 100, 155)],
        )
        self.assertEqual(text, spec)
        self.assertEqual(refused[0]["reason"], "duplicate_count_match")
        self.assertEqual(refused[0]["match_count"], 2)


def _apply_items_schema() -> None:
    """init_test_db apply_schema closure: build ``items`` via the backend factory."""
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _ITEMS_DDL)
        conn.commit()
    finally:
        conn.close()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class _FakeDB:
    """Backend-aware ``items`` seed DB used by patched resolvers."""

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

    def insert(self, item_id: int, spec: str) -> None:
        conn = connect_test_db(self.path)
        try:
            p = _p(conn)
            conn.execute(
                f"INSERT INTO items (id, spec) VALUES ({p}, {p})",
                (item_id, spec),
            )
            conn.commit()
        finally:
            conn.close()

    def fetch(self, item_id: int) -> Optional[str]:
        conn = connect_test_db(self.path)
        try:
            p = _p(conn)
            row = conn.execute(
                f"SELECT spec FROM items WHERE id = {p}", (item_id,),
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None


class _Harness:
    """Patch DB resolution + side-effects for in-test execute_structured_write."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._patches = []

    def __enter__(self):
        from yoke_core.domain import db_helpers as _db_helpers

        _path = {"return_value": self.db_path}
        self._patches = [
            mock.patch.object(backlog_queries, "_resolve_write_db_path", **_path),
            mock.patch.object(backlog_queries, "_assert_write_db_ready"),
            mock.patch.object(backlog_structured_write_op, "_resolve_write_db_path", **_path),
            mock.patch.object(backlog_structured_write_op, "_assert_write_db_ready"),
            mock.patch.object(_db_helpers, "resolve_db_path", **_path),
            mock.patch.object(backlog_rendering, "_render_body", return_value=True),
            mock.patch.object(backlog_rendering, "_sync_body", return_value=(True, "full")),
            mock.patch.object(backlog_rendering, "_record_sync_failure"),
            mock.patch.object(backlog_rendering, "_maybe_rebuild_board"),
            mock.patch("yoke_core.domain.idea_readiness_repair._emit_audit",
                       return_value=True),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        for p in self._patches:
            p.stop()


class TestAttemptStaleCountRepair(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tmp.name)
        self.db = _FakeDB()

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _write_repo_file(self, rel: str, lines: int) -> None:
        target = self.repo_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x\n" * lines)

    def _attempt(self, item_id: int, issues, *, rerun_pass: bool = True):
        rerun_value = ("pass", []) if rerun_pass else ("block", [])
        with _Harness(self.db.path), \
             mock.patch.object(
                 idea_readiness_repair, "_rerun_readiness",
                 return_value=rerun_value,
             ):
            return idea_readiness_repair.attempt_stale_count_repair(
                item_id=item_id, issues=issues, repo_root=self.repo_root,
            )

    def _attempt_raw(self, item_id: int, issues):
        """Real repair under ``_Harness`` only — for refusal paths that never
        reach (and so never need to mock) the re-run."""
        with _Harness(self.db.path):
            return idea_readiness_repair.attempt_stale_count_repair(
                item_id=item_id, issues=issues, repo_root=self.repo_root,
            )

    def test_pure_stale_repair_writes_and_passes(self):
        item_id = 1605000
        recorded, actual = 104, 155
        self.db.insert(item_id, _spec((_SAMPLE_PATH, recorded)))
        self._write_repo_file(_SAMPLE_PATH, actual)
        outcome = self._attempt(
            item_id, [_stale_issue(_SAMPLE_PATH, recorded, actual)],
        )
        self.assertTrue(outcome.success, msg=outcome.error)
        self.assertEqual(outcome.repaired_paths[0].actual, actual)
        new_spec = self.db.fetch(item_id) or ""
        self.assertIn(f"`{_SAMPLE_PATH}` = {actual}", new_spec)
        self.assertNotIn(f"`{_SAMPLE_PATH}` = {recorded}", new_spec)

    def test_missing_file_refused(self):
        item_id = 1605001
        spec_text = _spec(("ghost/missing.py", 50))
        self.db.insert(item_id, spec_text)
        outcome = self._attempt_raw(
            item_id, [_stale_issue("ghost/missing.py", 50, 0)])
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.refused_paths[0]["reason"], "missing_file")
        self.assertEqual(self.db.fetch(item_id), spec_text)

    def test_sibling_threshold_blocks_repair(self):
        item_id = 1605002
        self.db.insert(item_id, _spec((_OTHER_PATH, 200)))
        self._write_repo_file(_OTHER_PATH, 340)
        outcome = self._attempt_raw(
            item_id, [_stale_issue(_OTHER_PATH, 200, 340)])
        self.assertFalse(outcome.success)
        self.assertTrue(any(
            r.get("reason") == "missing_sibling_plan"
            for r in outcome.refused_paths
        ))

    def test_sibling_threshold_with_plan_allows_repair(self):
        item_id = 1605003
        spec_text = (
            _spec((_OTHER_PATH, 200))
            + "\nPlan: extract a new sibling module for the heavy logic.\n"
        )
        self.db.insert(item_id, spec_text)
        self._write_repo_file(_OTHER_PATH, 340)
        outcome = self._attempt(
            item_id, [_stale_issue(_OTHER_PATH, 200, 340)],
        )
        self.assertTrue(outcome.success, msg=outcome.error)
        self.assertIn(f"`{_OTHER_PATH}` = 340", self.db.fetch(item_id) or "")

    def test_mixed_classification_refuses(self):
        item_id = 1605004
        spec_text = _spec((_SAMPLE_PATH, 50))
        self.db.insert(item_id, spec_text)
        self._write_repo_file(_SAMPLE_PATH, 100)
        issues = [
            _stale_issue(_SAMPLE_PATH, 50, 100),
            {"code": "FILE_BUDGET_NOT_IN_CLAIM",
             "context": {"path": _OTHER_PATH}},
        ]
        outcome = self._attempt_raw(item_id, issues)
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.classification,
                         idea_readiness_repair.CLASS_MIXED_STALE_COUNT)
        self.assertIn("pure stale-count", outcome.error)
        self.assertEqual(self.db.fetch(item_id), spec_text)

    def test_empty_spec_refuses(self):
        item_id = 1605005
        self.db.insert(item_id, "")
        outcome = self._attempt_raw(item_id, [_stale_issue(_SAMPLE_PATH, 1)])
        self.assertFalse(outcome.success)
        self.assertIn("empty", outcome.error.lower())

    def test_structured_write_failure_surfaces(self):
        item_id = 1605006
        self.db.insert(item_id, _spec((_SAMPLE_PATH, 50)))
        self._write_repo_file(_SAMPLE_PATH, 80)
        write_fail = {"success": False, "error": "shrinkage guard blocked"}
        with _Harness(self.db.path), mock.patch.object(
                idea_readiness_repair, "execute_structured_write",
                return_value=write_fail):
            outcome = idea_readiness_repair.attempt_stale_count_repair(
                item_id=item_id, issues=[_stale_issue(_SAMPLE_PATH, 50, 80)],
                repo_root=self.repo_root,
            )
        self.assertFalse(outcome.success)
        self.assertIn("shrinkage", outcome.error)


class TestRepairOutcomePayload(unittest.TestCase):
    def test_payload_omits_empty_optional_fields(self):
        outcome = idea_readiness_repair.RepairOutcome(
            success=True,
            classification=idea_readiness_repair.CLASS_PURE_STALE_COUNT,
            item_id=42,
            repaired_paths=[idea_readiness_repair.RepairedPath("a.py", 10, 12)],
            field_written="spec", rerun_verdict="pass", audit_emitted=True,
        )
        payload = outcome.to_payload()
        self.assertTrue(payload["success"])
        for k in ("repaired_paths", "field_written", "rerun_verdict",
                  "audit_emitted"):
            self.assertIn(k, payload)
        for k in ("error", "refused_paths", "rerun_issues"):
            self.assertNotIn(k, payload)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
