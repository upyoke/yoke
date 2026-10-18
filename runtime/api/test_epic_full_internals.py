"""Internal helper tests for ``yoke_core.domain.epic``.

Covers cascade_task_status, orphan_check, _parse_epic_id, _validate_epic_exists, history_insert, and pipe helpers.

Split from ``test_epic_full.py``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import epic
from runtime.api.conftest import insert_epic_task, insert_item


class TestCascadeTaskStatus:
    def test_unknown_cascade_returns_zero(self, test_db):
        result = epic.cascade_task_status(test_db, "42", "idea", "done")
        assert result == "0"

    def test_no_eligible_tasks_returns_zero(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Task 1", "", "", "")
        epic.task_update_status(test_db, "42", 1, "implementing")
        # cascade planning -> plan-drafted won't match tasks in implementing
        result = epic.cascade_task_status(test_db, "42", "planning", "plan-drafted")
        assert result == "0"

    def test_cascade_map_entries(self):
        """Verify all expected cascade mappings exist."""
        expected_keys = [
            ("planning", "plan-drafted"),
            ("plan-drafted", "refining-plan"),
            ("refining-plan", "planned"),
            ("reviewed-implementation", "polishing-implementation"),
            ("polishing-implementation", "implemented"),
            ("implemented", "release"),
            ("release", "done"),
            # Reverse
            ("plan-drafted", "planning"),
            ("planned", "refining-plan"),
            ("refining-plan", "plan-drafted"),
            ("planned", "plan-drafted"),
            ("polishing-implementation", "reviewed-implementation"),
            ("implemented", "polishing-implementation"),
            ("release", "implemented"),
            ("done", "release"),
        ]
        for key in expected_keys:
            assert key in epic._CASCADE_MAP, f"Missing cascade key: {key}"


class TestOrphanCheck:
    def test_finds_orphans(self, test_db):
        # Epic 201: has tasks but no Technical Plan
        insert_item(
            test_db,
            id=201,
            title="Epic 201",
            workflow_id="epic",
            spec="Just a description",
        )
        insert_epic_task(test_db, epic_id=201, task_num=1, title="Task 1")

        # Epic 202: has tasks but null body
        insert_item(test_db, id=202, title="Epic 202", workflow_id="epic", spec=None)
        insert_epic_task(test_db, epic_id=202, task_num=1, title="Task 1")

        # Epic 200: has tasks AND Technical Plan (not orphan)
        insert_item(
            test_db,
            id=200,
            title="Epic 200",
            workflow_id="epic",
            technical_plan="Plan details here.",
        )
        insert_epic_task(test_db, epic_id=200, task_num=1, title="Task 1")

        result = epic.orphan_check(test_db)
        lines = [line for line in result.strip().split("\n") if line]
        assert len(lines) == 2
        assert "YOK-201" in result
        assert "YOK-202" in result
        assert "YOK-200" not in result

    def test_no_orphans(self, test_db):
        insert_item(
            test_db,
            id=200,
            title="Epic 200",
            workflow_id="epic",
            technical_plan="Plan details.",
        )
        insert_epic_task(test_db, epic_id=200, task_num=1, title="Task 1")
        result = epic.orphan_check(test_db)
        assert result == ""


class TestValidateEpicExists:
    def test_integer_without_tasks_raises(self, test_db):
        with pytest.raises(LookupError, match="not found in epic_tasks"):
            epic._validate_epic_exists(test_db, 42)

    def test_nonexistent_integer_raises(self, test_db):
        with pytest.raises(LookupError, match="not found in epic_tasks"):
            epic._validate_epic_exists(test_db, 999)

    def test_existing_integer_passes(self, test_db):
        insert_epic_task(test_db, epic_id=42, task_num=1, title="Task 1")
        epic._validate_epic_exists(test_db, 42)


class TestHistoryInsert:
    def test_returns_message(self, test_db):
        """history_insert returns a formatted message (subprocess may fail in test)."""
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        result = epic.history_insert(
            test_db,
            "42",
            1,
            "planning",
            "implementing",
            "First transition",
            scripts_dir="/nonexistent",
        )
        assert "Inserted history: 42/1 planning -> implementing" in result


class TestPipeHelpers:
    def test_pipe_row(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        row = test_db.execute(
            "SELECT id, epic_id, task_num, title FROM epic_tasks WHERE epic_id='42'"
        ).fetchone()
        result = epic._pipe_row(row, ["id", "epic_id", "task_num", "title"])
        parts = result.split("|")
        assert len(parts) == 4
        assert parts[1] == "42"
        assert parts[3] == "Widget"

    def test_pipe_row_null_values(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        row = test_db.execute(
            "SELECT id, body FROM epic_tasks WHERE epic_id='42'"
        ).fetchone()
        result = epic._pipe_row(row, ["id", "body"])
        # body is NULL -> empty string in pipe output
        assert result.endswith("|")
