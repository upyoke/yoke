"""Comprehensive pytest suite for ``yoke_core.domain.epic``.

Replaces the legacy epic shell suite with pytest coverage, plus additional
edge-case coverage.

Uses the shared ``test_db`` fixture from ``conftest.py`` for in-memory DB setup.

Sibling modules cover related surfaces:

- ``test_epic_full_dispatch.py`` — file ops, dispatch chains, progress notes.
- ``test_epic_full_review.py`` — review_get, simulation parsing, simulation_get.
- ``test_epic_full_internals.py`` — cascade, orphans, migrations, helpers.
"""

from __future__ import annotations

from typing import Optional

import pytest

from yoke_core.domain import epic

TEST_EPIC_ID = 42
TEST_EPIC_REF = f"YOK-{TEST_EPIC_ID}"
TEST_EPIC_BRANCH = TEST_EPIC_REF
TEST_EPIC_BRANCH_NEXT = f"{TEST_EPIC_REF}-new"
TEST_EPIC_WORKTREE_PATH = f"/tmp/worktrees/{TEST_EPIC_REF}"


def _p(conn) -> str:
    return epic._placeholder(conn)


def _task_row(conn, epic_id: int, task_num: int):
    return conn.execute(
        f"SELECT * FROM epic_tasks WHERE epic_id={_p(conn)} AND task_num={_p(conn)}",
        (str(epic_id), task_num),
    ).fetchone()


def _task_field(conn, epic_id: int, task_num: int, field: str):
    row = _task_row(conn, epic_id, task_num)
    return row[field] if row else None


class TestTaskUpsert:
    def test_basic_upsert(self, test_db):
        result = epic.task_upsert(test_db, "42", 1, "Create the widget", "feature/widget", "50k", "none")
        assert "Upserted task 42/1" in result

        row = _task_row(test_db, 42, 1)
        assert row is not None
        assert row["title"] == "Create the widget"
        assert row["worktree"] == "feature/widget"
        assert row["context_estimate"] == "50k"
        assert row["dependencies"] == "none"
        assert row["status"] == "planning"

    def test_upsert_updates_title_and_worktree(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Create the widget", "feature/widget", "50k", "none")
        result = epic.task_upsert(test_db, "42", 1, "Create the better widget", "feature/widget-v2", "50k", "none")
        assert "Upserted task 42/1" in result

        row = _task_row(test_db, 42, 1)
        assert row["title"] == "Create the better widget"
        assert row["worktree"] == "feature/widget-v2"

    def test_upsert_no_duplicates(self, test_db):
        epic.task_upsert(test_db, "42", 1, "First", "", "", "")
        epic.task_upsert(test_db, "42", 1, "Second", "", "", "")
        count = test_db.execute(
            "SELECT COUNT(*) FROM epic_tasks WHERE epic_id='42' AND task_num=1"
        ).fetchone()[0]
        assert count == 1

    def test_worktree_preserved_on_empty_re_upsert(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "feature/widget-v2", "", "")
        wt_before = _task_field(test_db, 42, 1, "worktree")
        assert wt_before == "feature/widget-v2"

        epic.task_upsert(test_db, "42", 1, "Widget updated", "", "", "")
        wt_after = _task_field(test_db, 42, 1, "worktree")
        assert wt_after == "feature/widget-v2"

    def test_worktree_overwritten_by_non_empty(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "feature/widget-v2", "", "")
        epic.task_upsert(test_db, "42", 1, "Widget", "feature/widget-v3", "", "")
        wt = _task_field(test_db, 42, 1, "worktree")
        assert wt == "feature/widget-v3"

    def test_initial_empty_worktree(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        wt = _task_field(test_db, 42, 1, "worktree")
        assert wt == ""

    def test_special_characters_in_title(self, test_db):
        title = "Title with 'quotes' and \"doubles\" & <angle>"
        epic.task_upsert(test_db, "42", 1, title, "", "", "")
        stored = _task_field(test_db, 42, 1, "title")
        assert stored == title

    def test_title_length_validation(self, test_db):
        long_title = "x" * 101
        with pytest.raises(ValueError, match="exceeds 100 characters"):
            epic.task_upsert(test_db, "42", 1, long_title)

    def test_empty_title_rejected(self, test_db):
        with pytest.raises(ValueError, match="title is required"):
            epic.task_upsert(test_db, "42", 1, "")


class TestTaskGet:
    def test_basic_get(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "feat", "M", "none")
        result = epic.task_get(test_db, "42", 1)
        assert "42" in result
        assert "Widget" in result
        assert "planning" in result
        # Pipe-delimited with 8 separators (9 fields)
        assert result.count("|") == 8

    def test_not_found_raises(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        with pytest.raises(LookupError, match="not found"):
            epic.task_get(test_db, "42", 999)

    def test_sun_prefix_stripped(self, test_db):
        epic.task_upsert(test_db, str(TEST_EPIC_ID), 1, "Widget", "", "", "")
        result = epic.task_get(test_db, str(TEST_EPIC_ID), 1)
        # Ensure calling with YOK- prefix also works (parse_epic_id strips it)
        result2 = epic.task_get(test_db, epic._parse_epic_id(TEST_EPIC_REF), 1)
        assert result == result2


class TestTaskList:
    def test_list_multiple_tasks(self, test_db):
        for i in range(1, 7):
            epic.task_upsert(test_db, "42", i, f"Task {i}", "", "", "")
        result = epic.task_list(test_db, "42")
        lines = result.strip().split("\n")
        assert len(lines) == 6

    def test_ordering_by_task_num(self, test_db):
        epic.task_upsert(test_db, "42", 3, "Third", "", "", "")
        epic.task_upsert(test_db, "42", 1, "First", "", "", "")
        epic.task_upsert(test_db, "42", 2, "Second", "", "", "")
        result = epic.task_list(test_db, "42")
        lines = result.strip().split("\n")
        # task_num is 3rd field (index 2)
        assert lines[0].split("|")[2] == "1"
        assert lines[1].split("|")[2] == "2"
        assert lines[2].split("|")[2] == "3"

    def test_empty_epic(self, test_db):
        result = epic.task_list(test_db, "42")
        assert result == ""


class TestTaskUpdateStatus:
    def test_update_status(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        result = epic.task_update_status(test_db, "42", 1, "implementing")
        assert "Updated status of 42/1 to implementing" in result
        assert _task_field(test_db, 42, 1, "status") == "implementing"

    def test_invalid_status_rejected(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        with pytest.raises(ValueError, match="invalid epic task status"):
            epic.task_update_status(test_db, "42", 1, "bogus")

    def test_not_found(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        with pytest.raises(LookupError, match="not found"):
            epic.task_update_status(test_db, "42", 888, "implementing")

    def test_terminal_status_blocked_without_pipeline(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        epic.task_update_status(test_db, "42", 1, "implementing")
        with pytest.raises(PermissionError, match="pipeline-owned"):
            epic.task_update_status(test_db, "42", 1, "done")

    def test_terminal_status_allowed_with_pipeline(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        epic.task_update_status(test_db, "42", 1, "implementing")
        epic.task_update_status(test_db, "42", 1, "done", pipeline=True)
        assert _task_field(test_db, 42, 1, "status") == "done"

    def test_reviewed_implementation_blocked_without_pipeline(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        epic.task_update_status(test_db, "42", 1, "implementing")
        with pytest.raises(PermissionError):
            epic.task_update_status(test_db, "42", 1, "reviewed-implementation")

    def test_release_blocked_without_pipeline(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        epic.task_update_status(test_db, "42", 1, "implementing")
        with pytest.raises(PermissionError):
            epic.task_update_status(test_db, "42", 1, "release")

    def test_release_with_pipeline(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        epic.task_update_status(test_db, "42", 1, "release", pipeline=True)
        assert _task_field(test_db, 42, 1, "status") == "release"

    def test_implementing_without_pipeline_succeeds(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        epic.task_update_status(test_db, "42", 1, "implementing")
        assert _task_field(test_db, 42, 1, "status") == "implementing"

    def test_retired_statuses_rejected(self, test_db):
        """Statuses from old lifecycle that are no longer valid."""
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        for retired in ("active", "pending", "review", "ready"):
            with pytest.raises(ValueError, match="invalid epic task status"):
                epic.task_update_status(test_db, "42", 1, retired)
            # Status unchanged
            assert _task_field(test_db, 42, 1, "status") == "planning"

    def test_error_message_lists_valid_statuses(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        with pytest.raises(ValueError) as exc_info:
            epic.task_update_status(test_db, "42", 1, "bogus")
        msg = str(exc_info.value)
        for expected in ("implementing", "reviewing-implementation", "reviewed-implementation",
                         "done", "failed", "blocked", "stopped"):
            assert expected in msg


class TestTaskBody:
    def test_round_trip(self, test_db):
        epic.task_upsert(test_db, "42", 10, "Body test", "", "", "")
        body_input = "## Test body\n\nWith **markdown** and special chars: <>&\"'"
        result = epic.task_update_body(test_db, "42", 10, body_input)
        assert "Updated body of 42/10" in result

        retrieved = epic.task_get_body(test_db, "42", 10)
        assert retrieved == body_input

    def test_body_file_update(self, test_db, tmp_path):
        epic.task_upsert(test_db, "42", 10, "Body test", "", "", "")
        body_input = "## Test body from file\n\nWith content."
        f = tmp_path / "body.md"
        f.write_text(body_input)

        # Simulate --body-file by reading and passing
        content = f.read_text()
        epic.task_update_body(test_db, "42", 10, content)
        assert epic.task_get_body(test_db, "42", 10) == body_input

    def test_get_body_not_found(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        with pytest.raises(LookupError, match="not found"):
            epic.task_get_body(test_db, "42", 999)

    def test_get_body_empty(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        body = epic.task_get_body(test_db, "42", 1)
        assert body == ""

    def test_update_body_not_found(self, test_db):
        with pytest.raises(LookupError, match="not found"):
            epic.task_update_body(test_db, "42", 999, "body text")


class TestTaskUpdateField:
    def test_update_github_issue(self, test_db):
        epic.task_upsert(test_db, "42", 20, "Field test", "", "", "")
        result = epic.task_update_field(test_db, "42", 20, "github_issue", "42")
        assert "Updated github_issue of 42/20 to 42" in result
        assert _task_field(test_db, 42, 20, "github_issue") == "42"

    def test_update_dispatch_attempts(self, test_db):
        epic.task_upsert(test_db, "42", 20, "Field test", "", "", "")
        epic.task_update_field(test_db, "42", 20, "dispatch_attempts", "3")
        # SQLite stores as integer due to column affinity
        assert str(_task_field(test_db, 42, 20, "dispatch_attempts")) == "3"

    def test_update_agent_id(self, test_db):
        epic.task_upsert(test_db, "42", 20, "Field test", "", "", "")
        epic.task_update_field(test_db, "42", 20, "agent_id", "agent-abc-123")
        assert _task_field(test_db, 42, 20, "agent_id") == "agent-abc-123"

    def test_invalid_field_rejected(self, test_db):
        epic.task_upsert(test_db, "42", 20, "Field test", "", "", "")
        with pytest.raises(ValueError, match="invalid field"):
            epic.task_update_field(test_db, "42", 20, "bogus_field", "val")

    def test_not_found(self, test_db):
        epic.task_upsert(test_db, "42", 20, "Field test", "", "", "")
        with pytest.raises(LookupError, match="not found"):
            epic.task_update_field(test_db, "42", 999, "github_issue", "42")

    def test_status_via_update_field_delegates(self, test_db):
        """task_update_field with field=status delegates to task_update_status."""
        epic.task_upsert(test_db, "42", 20, "Field test", "", "", "")
        epic.task_update_field(test_db, "42", 20, "status", "implementing")
        assert _task_field(test_db, 42, 20, "status") == "implementing"

    def test_status_via_update_field_validates(self, test_db):
        epic.task_upsert(test_db, "42", 20, "Field test", "", "", "")
        with pytest.raises(ValueError, match="invalid epic task status"):
            epic.task_update_field(test_db, "42", 20, "status", "invalid_value")

    def test_worktree_related_fields(self, test_db):
        """AC-5 from shell tests: worktree, branch, worktree_path fields."""
        epic.task_upsert(test_db, str(TEST_EPIC_ID), 1, "Widget", "", "", "")
        epic.task_update_field(test_db, str(TEST_EPIC_ID), 1, "worktree", TEST_EPIC_BRANCH)
        epic.task_update_field(test_db, str(TEST_EPIC_ID), 1, "branch", TEST_EPIC_BRANCH)
        epic.task_update_field(
            test_db, str(TEST_EPIC_ID), 1, "worktree_path", TEST_EPIC_WORKTREE_PATH
        )

        assert _task_field(test_db, TEST_EPIC_ID, 1, "worktree") == TEST_EPIC_BRANCH
        assert _task_field(test_db, TEST_EPIC_ID, 1, "branch") == TEST_EPIC_BRANCH
        assert _task_field(test_db, TEST_EPIC_ID, 1, "worktree_path") == TEST_EPIC_WORKTREE_PATH

        # Verify no partial null state
        null_count = test_db.execute(
            f"SELECT COUNT(*) FROM epic_tasks WHERE epic_id='{TEST_EPIC_ID}' AND task_num=1 "
            "AND (worktree IS NULL OR branch IS NULL OR worktree_path IS NULL)"
        ).fetchone()[0]
        assert null_count == 0

        # Updating worktree preserves branch and worktree_path
        epic.task_update_field(test_db, str(TEST_EPIC_ID), 1, "worktree", TEST_EPIC_BRANCH_NEXT)
        assert _task_field(test_db, TEST_EPIC_ID, 1, "branch") == TEST_EPIC_BRANCH
        assert _task_field(test_db, TEST_EPIC_ID, 1, "worktree_path") == TEST_EPIC_WORKTREE_PATH
