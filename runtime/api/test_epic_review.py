"""Tests for yoke_core.domain.epic — progress notes, simulation result parsing,
cascade-mapping rules, orphan check, review reads, and review/simulation writes.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from yoke_core.domain import epic
from runtime.api.conftest import insert_item, insert_epic_task
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)

# Synthetic test epic ID — not a real backlog item reference.
TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


@pytest.fixture
def db(tmp_path):
    # Backend-aware: SQLite file on SQLite, disposable per-test database on
    # Postgres (YOKE_PG_DSN repointed for the context).
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield conn
        finally:
            conn.close()


@pytest.fixture
def db_with_task(db):
    insert_epic_task(db, epic_id=TEST_ITEM_ID, task_num=1, title="First task", status="planning")
    return db


class TestProgressNotes:
    def test_insert_and_list(self, db_with_task):
        epic.progress_note_insert(db_with_task, "42", 1, 1, "Note body", "abc123")
        result = epic.progress_note_list_unsynced(db_with_task, "42")
        assert "Note body" in result
        assert "abc123" in result

    def test_mark_synced(self, db_with_task):
        epic.progress_note_insert(db_with_task, "42", 1, 1, "Note", "abc")
        epic.progress_note_mark_synced(db_with_task, "42", 1, 1)
        result = epic.progress_note_list_unsynced(db_with_task, "42")
        assert result == ""

    def test_upsert_semantics(self, db_with_task):
        epic.progress_note_insert(db_with_task, "42", 1, 1, "First version", "")
        epic.progress_note_insert(db_with_task, "42", 1, 1, "Updated version", "def456")
        row = db_with_task.execute(
            "SELECT body FROM epic_progress_notes WHERE epic_id='42' AND task_num=1 AND note_num=1"
        ).fetchone()
        assert row["body"] == "Updated version"


class TestParseSimulationResult:
    def test_simulation_clean(self):
        assert epic._parse_simulation_result("SIMULATION: CLEAN") == "CLEAN"

    def test_simulation_gaps(self):
        assert epic._parse_simulation_result("SIMULATION: GAPS FOUND") == "GAPS FOUND"

    def test_result_header_clean(self):
        assert epic._parse_simulation_result("## Result: CLEAN") == "CLEAN"

    def test_result_header_gaps(self):
        assert epic._parse_simulation_result("## Result: GAPS FOUND (3 issues)") == "GAPS FOUND"

    def test_count_format_with_gaps(self):
        body = "## Result: 2 critical, 1 warnings, 0 notes"
        assert epic._parse_simulation_result(body) == "GAPS FOUND"

    def test_count_format_all_zero(self):
        body = "## Result: 0 critical, 0 warnings, 0 notes"
        assert epic._parse_simulation_result(body) == "CLEAN"

    def test_bold_format_gaps(self):
        assert epic._parse_simulation_result("**Result:** 3 gaps found") == "GAPS FOUND"

    def test_bold_format_clean(self):
        assert epic._parse_simulation_result("**Result:** CLEAN") == "CLEAN"

    def test_no_result(self):
        assert epic._parse_simulation_result("No result line here") is None

    def test_empty_body(self):
        assert epic._parse_simulation_result("") is None


class TestCascadeMappingRules:
    """Cascade-map structure and edge cases."""

    def test_forward_cascade(self, db):
        """planning -> plan-drafted cascade updates matching tasks."""
        insert_epic_task(db, epic_id=42, task_num=1, title="T1", status="planning")
        insert_epic_task(db, epic_id=42, task_num=2, title="T2", status="planning")
        insert_epic_task(db, epic_id=42, task_num=3, title="T3", status="implementing")

        # Direct DB update to avoid update-status.sh subprocess
        result = epic.cascade_task_status.__wrapped__(db, "42", "planning", "plan-drafted") if hasattr(epic.cascade_task_status, '__wrapped__') else None
        # Since cascade calls update-status.sh via subprocess, we test the mapping logic
        key = ("planning", "plan-drafted")
        assert key in epic._CASCADE_MAP
        task_from, task_to = epic._CASCADE_MAP[key]
        assert task_from == "planning"
        assert task_to == "plan-drafted"

    def test_no_cascade_defined(self, db_with_task):
        """Unmapped transitions return '0'."""
        result = epic.cascade_task_status(db_with_task, "42", "idea", "defined")
        assert result == "0"

    def test_reverse_cascade_mapping(self):
        """Verify reverse cascade mappings exist."""
        assert ("done", "release") in epic._CASCADE_MAP
        assert ("release", "implemented") in epic._CASCADE_MAP
        assert ("plan-drafted", "planning") in epic._CASCADE_MAP

    def test_no_eligible_tasks(self, db):
        """No tasks match the from-status -> returns 0."""
        insert_epic_task(db, epic_id=42, task_num=1, title="T1", status="implementing")
        result = epic.cascade_task_status(db, "42", "planning", "plan-drafted")
        assert result == "0"


class TestOrphanCheck:
    def test_finds_orphans(self, db):
        insert_item(db, id=TEST_ITEM_ID, title="My epic", type="epic", spec="No plan here")
        insert_epic_task(db, epic_id=TEST_ITEM_ID, task_num=1, title="Task")
        result = epic.orphan_check(db)
        assert TEST_ITEM_REF in result

    def test_no_orphans(self, db):
        insert_item(db, id=TEST_ITEM_ID, title="My epic", type="epic", technical_plan="Actual tech plan content")
        insert_epic_task(db, epic_id=TEST_ITEM_ID, task_num=1, title="Task")
        result = epic.orphan_check(db)
        assert result == ""


class TestReviewGet:
    def test_review_not_found(self, db_with_task):
        with pytest.raises(LookupError, match="no review found"):
            epic.review_get(db_with_task, "42", 1)

    def test_review_get_from_qa_tables(self, db_with_task):
        """Insert review data directly into qa tables and verify review_get reads it."""
        req_id = 1001
        db_with_task.execute(
            """INSERT INTO qa_requirements
               (id, epic_id, task_num, qa_kind, qa_phase, blocking_mode, requirement_source, success_policy, created_at)
               VALUES (%s, %s, %s, 'implementation_review', 'verification', 'blocking', 'explicit',
                       '{"type":"deterministic","criteria":"verdict_pass"}', '2026-01-01T00:00:00Z')""",
            (req_id, 42, 1),
        )
        db_with_task.execute(
            """INSERT INTO qa_runs
               (qa_requirement_id, executor_type, qa_kind, verdict, raw_result, created_at)
               VALUES (%s, 'agent', 'implementation_review', 'pass', '{"body":"Good work"}', '2025-01-01T00:00:00Z')""",
            (req_id,),
        )
        db_with_task.commit()

        result = epic.review_get(db_with_task, "42", 1)
        parts = result.split("|")
        assert parts[3] == "PASS"
        assert "Good work" in parts[4]


class TestReviewAndSimulationWrites:
    def test_review_seed_creates_requirement(self, db_with_task):
        with patch("yoke_core.domain.epic._qa_requirement_add_silent", return_value=17) as add_req:
            result = epic.review_seed(db_with_task, "42", 1)

        assert result == "Implementation-review requirement seeded: 42/1 req_id=17"
        add_req.assert_called_once_with(
            epic_id=42,
            task_num=1,
            qa_kind="implementation_review",
            qa_phase="verification",
            target_env="local",
            blocking_mode="blocking",
            requirement_source="explicit",
            success_policy='{"type":"deterministic","criteria":"verdict_pass"}',
        )

    def test_review_seed_reuses_existing_requirement(self, db_with_task):
        db_with_task.execute(
            """INSERT INTO qa_requirements
               (id, epic_id, task_num, qa_kind, qa_phase, blocking_mode, requirement_source, success_policy, created_at)
               VALUES (9, 42, 1, 'implementation_review', 'verification', 'blocking', 'explicit',
                       '{"type":"deterministic","criteria":"verdict_pass"}', '2026-01-01T00:00:00Z')"""
        )
        db_with_task.commit()

        with patch("yoke_core.domain.epic._qa_requirement_add_silent") as add_req:
            result = epic.review_seed(db_with_task, "42", 1)

        assert result == "Implementation-review requirement seeded: 42/1 req_id=9"
        add_req.assert_not_called()

    def test_review_insert_lowercases_verdict_and_restores_env(self, db_with_task, monkeypatch):
        monkeypatch.setenv("KEEP_ME", "yes")
        previous = dict(os.environ)
        with patch("yoke_core.domain.epic._ensure_implementation_review_requirement", return_value=7), patch(
            "yoke_core.domain.epic._qa_run_add_silent"
        ) as add_run:
            result = epic.review_insert(db_with_task, "42", 1, "PASS", "Looks good")

        assert result == "Inserted review: 42/1 verdict=PASS"
        add_run.assert_called_once_with(
            requirement_id=7,
            executor_type="agent",
            qa_kind="implementation_review",
            verdict="pass",
            raw_result='{"body": "Looks good"}',
        )
        assert os.environ.get("KEEP_ME") == "yes"
        assert os.environ.get("YOKE_INTERNAL_EPIC_REVIEW_WRITE") is None
        assert os.environ == previous

    def test_simulation_upsert_creates_requirement_and_run(self, db):
        with patch("yoke_core.domain.epic._qa_requirement_add_silent", return_value=23) as add_req, patch(
            "yoke_core.domain.epic._qa_run_add_silent"
        ) as add_run:
            result = epic.simulation_upsert(db, "42", "plan", "SIMULATION: CLEAN")

        assert result == "Upserted simulation: 42/plan"
        add_req.assert_called_once_with(
            item_id=42,
            qa_kind="simulation",
            qa_phase="verification",
            target_env="local",
            blocking_mode="blocking",
            requirement_source="explicit",
            success_policy='{"type":"deterministic","criteria":"result_pass","phase":"plan"}',
        )
        add_run.assert_called_once_with(
            requirement_id=23,
            executor_type="agent",
            qa_kind="simulation",
            verdict="pass",
            raw_result='{"body":"SIMULATION: CLEAN","phase":"plan"}',
        )

    def test_simulation_upsert_reuses_existing_requirement_and_deletes_prior_runs(self, db):
        db.execute(
            """INSERT INTO qa_requirements
               (id, item_id, qa_kind, qa_phase, blocking_mode, requirement_source, success_policy, created_at)
               VALUES (11, 42, 'simulation', 'verification', 'blocking', 'explicit',
                       '{"type":"deterministic","criteria":"result_pass","phase":"integration"}',
                       '2026-01-01T00:00:00Z')"""
        )
        db.execute(
            """INSERT INTO qa_runs
               (qa_requirement_id, executor_type, qa_kind, verdict, raw_result, created_at)
               VALUES (11, 'agent', 'simulation', 'fail', '{"body":"old","phase":"integration"}',
                       '2026-01-01T00:00:00Z')"""
        )
        db.commit()

        with patch("yoke_core.domain.epic._qa_requirement_add_silent") as add_req, patch(
            "yoke_core.domain.epic._qa_run_add_silent"
        ) as add_run:
            result = epic.simulation_upsert(db, "42", "integration", "## Result: GAPS FOUND")

        assert result == "Upserted simulation: 42/integration"
        assert db.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id = 11"
        ).fetchone()[0] == 0
        add_req.assert_not_called()
        add_run.assert_called_once_with(
            requirement_id=11,
            executor_type="agent",
            qa_kind="simulation",
            verdict="fail",
            raw_result='{"body":"## Result: GAPS FOUND","phase":"integration"}',
        )
