"""Tests for yoke_core.domain.epic — task CRUD, status, body, files, history."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from yoke_core.domain import epic
from runtime.api.conftest import insert_epic_task

# Synthetic test epic ID — not a real backlog item reference.
TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


@pytest.fixture
def db(test_db):
    """Full Yoke schema on the disposable Postgres authority fixture."""
    return test_db


@pytest.fixture
def db_with_task(db):
    """DB with one epic task already inserted."""
    insert_epic_task(db, epic_id=TEST_ITEM_ID, task_num=1, title="First task", status="planning")
    return db


class TestTaskUpsert:
    def test_insert_new_task(self, db):
        result = epic.task_upsert(db, "42", 1, "My task", TEST_ITEM_REF, "M", "")
        assert "Upserted task 42/1" in result

        row = db.execute("SELECT * FROM epic_tasks WHERE epic_id='42' AND task_num=1").fetchone()
        assert row is not None
        assert row["title"] == "My task"
        assert row["status"] == "planning"

    def test_upsert_preserves_existing_status(self, db_with_task):
        # Change status first
        db_with_task.execute(
            "UPDATE epic_tasks SET status='implementing' WHERE epic_id='42' AND task_num=1"
        )
        db_with_task.commit()

        # Upsert should preserve status
        epic.task_upsert(db_with_task, "42", 1, "Updated title", "", "L", "001")
        row = db_with_task.execute("SELECT * FROM epic_tasks WHERE epic_id='42' AND task_num=1").fetchone()
        assert row["status"] == "implementing"
        assert row["title"] == "Updated title"

    def test_upsert_preserves_worktree_when_empty(self, db):
        epic.task_upsert(db, "42", 1, "Task", TEST_ITEM_REF, "", "")
        epic.task_upsert(db, "42", 1, "Task updated", "", "", "")
        row = db.execute("SELECT worktree FROM epic_tasks WHERE epic_id='42' AND task_num=1").fetchone()
        assert row["worktree"] == TEST_ITEM_REF

    def test_title_length_limit(self, db):
        with pytest.raises(ValueError, match="100 characters"):
            epic.task_upsert(db, "42", 1, "x" * 101, "", "", "")

    def test_empty_title_raises(self, db):
        with pytest.raises(ValueError, match="title is required"):
            epic.task_upsert(db, "42", 1, "", "", "", "")


class TestTaskGet:
    def test_get_existing(self, db_with_task):
        result = epic.task_get(db_with_task, "42", 1)
        parts = result.split("|")
        assert parts[1] == "42"  # epic_id
        assert parts[2] == "1"  # task_num
        assert parts[3] == "First task"  # title
        assert parts[7] == "planning"  # status

    def test_get_not_found(self, db):
        with pytest.raises(LookupError, match="not found"):
            epic.task_get(db, "42", 99)


class TestTaskList:
    def test_list_tasks(self, db):
        insert_epic_task(db, epic_id=42, task_num=1, title="Task 1")
        insert_epic_task(db, epic_id=42, task_num=2, title="Task 2")
        result = epic.task_list(db, "42")
        lines = result.strip().split("\n")
        assert len(lines) == 2
        assert "Task 1" in lines[0]
        assert "Task 2" in lines[1]

    def test_list_empty(self, db):
        result = epic.task_list(db, "99")
        assert result == ""


class TestTaskUpdateStatus:
    def test_valid_status(self, db_with_task):
        result = epic.task_update_status(
            db_with_task, "42", 1, "implementing", pipeline=True
        )
        assert "implementing" in result
        row = db_with_task.execute("SELECT status FROM epic_tasks WHERE epic_id='42' AND task_num=1").fetchone()
        assert row["status"] == "implementing"

    def test_invalid_status_raises(self, db_with_task):
        with pytest.raises(ValueError, match="invalid epic task status"):
            epic.task_update_status(db_with_task, "42", 1, "bogus")

    def test_terminal_status_blocked_without_pipeline(self, db_with_task):
        with pytest.raises(PermissionError, match="terminal status"):
            epic.task_update_status(db_with_task, "42", 1, "done")

    def test_terminal_status_allowed_with_pipeline(self, db_with_task):
        result = epic.task_update_status(db_with_task, "42", 1, "done", pipeline=True)
        assert "done" in result

    def test_not_found(self, db):
        with pytest.raises(LookupError, match="not found"):
            epic.task_update_status(db, "42", 99, "implementing")

    def test_status_sync_uses_python_owner(self, db_with_task):
        with patch("yoke_core.domain.epic.epic_task_sync.sync_task_label", return_value=0) as sync:
            epic.task_update_status(db_with_task, "42", 1, "implementing")

        sync.assert_called_once()
        assert sync.call_args.args == ("42", 1, "implementing")

    def test_pipeline_status_skips_python_sync(self, db_with_task):
        with patch("yoke_core.domain.epic.epic_task_sync.sync_task_label", return_value=0) as sync:
            epic.task_update_status(db_with_task, "42", 1, "implemented", pipeline=True)

        sync.assert_not_called()


class TestTaskBody:
    def test_update_and_get_body(self, db_with_task):
        epic.task_update_body(db_with_task, "42", 1, "Hello world")
        result = epic.task_get_body(db_with_task, "42", 1)
        assert result == "Hello world"

    def test_update_body_not_found(self, db):
        with pytest.raises(LookupError, match="not found"):
            epic.task_update_body(db, "42", 99, "body")

    def test_get_body_not_found(self, db):
        with pytest.raises(LookupError, match="not found"):
            epic.task_get_body(db, "42", 99)

    def test_get_body_null_returns_empty(self, db_with_task):
        result = epic.task_get_body(db_with_task, "42", 1)
        assert result == ""

    def test_update_body_uses_python_sync_owner(self, db_with_task):
        with patch("yoke_core.domain.epic.epic_task_sync.sync_task_body", return_value=0) as sync:
            epic.task_update_body(db_with_task, "42", 1, "Hello world")

        sync.assert_called_once()
        assert sync.call_args.args == ("42", 1)


class TestTaskUpdateField:
    def test_update_valid_field(self, db_with_task):
        result = epic.task_update_field(db_with_task, "42", 1, "blocked_by", "YOK-100")
        assert "Updated blocked_by" in result

    def test_invalid_field_raises(self, db_with_task):
        with pytest.raises(ValueError, match="invalid field"):
            epic.task_update_field(db_with_task, "42", 1, "nonexistent", "x")

    def test_status_delegates(self, db_with_task):
        """Status field delegates to task_update_status for validation."""
        with pytest.raises(PermissionError, match="terminal status"):
            epic.task_update_field(db_with_task, "42", 1, "status", "done")


class TestFiles:
    def test_add_and_list(self, db_with_task):
        epic.file_add(db_with_task, "42", 1, "src/main.py", "create")
        epic.file_add(db_with_task, "42", 1, "tests/test.py", "modify")
        result = epic.file_list(db_with_task, "42", 1)
        lines = result.strip().split("\n")
        assert len(lines) == 2
        assert "src/main.py" in result
        assert "tests/test.py" in result

    def test_upsert_semantics(self, db_with_task):
        epic.file_add(db_with_task, "42", 1, "src/main.py", "create")
        epic.file_add(db_with_task, "42", 1, "src/main.py", "modify")
        result = epic.file_list(db_with_task, "42", 1)
        lines = result.strip().split("\n")
        assert len(lines) == 1
        assert "modify" in result


class TestHistoryInsert:
    def test_basic(self, db_with_task):
        result = epic.history_insert(db_with_task, "42", 1, "planning", "implementing", "test note")
        assert "planning -> implementing" in result
