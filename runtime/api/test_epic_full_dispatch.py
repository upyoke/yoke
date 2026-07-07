"""File operations, dispatch chains, and progress notes for ``yoke_core.domain.epic``.

Split from ``test_epic_full.py``.

Uses the shared ``test_db`` fixture from ``conftest.py``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import epic

TEST_EPIC_ID = 42
TEST_EPIC_REF = f"YOK-{TEST_EPIC_ID}"
TEST_EPIC_WORKTREE_PATH = f"/tmp/worktrees/{TEST_EPIC_REF}"


def _p(conn) -> str:
    return epic._placeholder(conn)


class TestFileOperations:
    def test_add_and_list(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        result = epic.file_add(test_db, "42", 1, "src/widget.sh", "create")
        assert "Added file src/widget.sh" in result

        epic.file_add(test_db, "42", 1, "tests/test-widget.sh", "create")
        epic.file_add(test_db, "42", 1, "CHANGELOG.md", "modify")

        listing = epic.file_list(test_db, "42", 1)
        lines = listing.strip().split("\n")
        assert len(lines) == 3
        assert "src/widget.sh" in listing
        assert "tests/test-widget.sh" in listing
        assert "modify" in listing

    def test_empty_file_list(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        result = epic.file_list(test_db, "42", 1)
        assert result == ""

    def test_duplicate_file_replaces(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        epic.file_add(test_db, "42", 1, "src/widget.sh", "create")
        count1 = test_db.execute(
            "SELECT COUNT(*) FROM epic_task_files WHERE epic_id='42' AND task_num=1"
        ).fetchone()[0]
        assert count1 == 1

        # Re-add with different action
        epic.file_add(test_db, "42", 1, "src/widget.sh", "modify")
        count2 = test_db.execute(
            "SELECT COUNT(*) FROM epic_task_files WHERE epic_id='42' AND task_num=1"
        ).fetchone()[0]
        assert count2 == 1

        listing = epic.file_list(test_db, "42", 1)
        assert "modify" in listing


class TestDispatchChains:
    def test_upsert_and_get(self, test_db):
        data = {
            "worktree_path": TEST_EPIC_WORKTREE_PATH,
            "queue": [1, 2, 3],
            "current_index": 0,
            "current_task": "1",
            "current_attempt": 1,
            "max_attempts": 5,
            "no_chain": 0,
        }
        result = epic.dispatch_chain_upsert(test_db, "42", "feature-wt1", data)
        assert "Upserted dispatch chain: 42/feature-wt1" in result

        chain = epic.dispatch_chain_get(test_db, "42", "feature-wt1")
        fields = chain.split("|")
        assert fields[1] == "42"  # epic_id
        assert fields[2] == "feature-wt1"  # worktree
        assert fields[3] == TEST_EPIC_WORKTREE_PATH  # worktree_path

    def test_get_not_found(self, test_db):
        with pytest.raises(LookupError, match="not found"):
            epic.dispatch_chain_get(test_db, "42", "nonexistent")

    def test_update_field(self, test_db):
        data = {"queue": [1, 2], "current_index": 0, "current_task": "1"}
        epic.dispatch_chain_upsert(test_db, "42", "wt1", data)
        epic.dispatch_chain_update(test_db, "42", "wt1", "current_task", "2")
        chain = epic.dispatch_chain_get(test_db, "42", "wt1")
        assert "2" in chain.split("|")[6]  # current_task

    def test_update_invalid_field(self, test_db):
        data = {"queue": [1, 2]}
        epic.dispatch_chain_upsert(test_db, "42", "wt1", data)
        with pytest.raises(ValueError, match="invalid field"):
            epic.dispatch_chain_update(test_db, "42", "wt1", "bogus", "val")

    def test_update_not_found(self, test_db):
        with pytest.raises(LookupError, match="not found"):
            epic.dispatch_chain_update(test_db, "42", "nonexist", "current_task", "1")

    def test_list(self, test_db):
        epic.dispatch_chain_upsert(test_db, "42", "wt1", {"queue": [1]})
        epic.dispatch_chain_upsert(test_db, "42", "wt2", {"queue": [2]})
        result = epic.dispatch_chain_list(test_db, "42")
        lines = result.strip().split("\n")
        assert len(lines) == 2

    def test_list_empty(self, test_db):
        result = epic.dispatch_chain_list(test_db, "42")
        assert result == ""

    def test_advance(self, test_db):
        data = {"queue": [10, 20, 30], "current_index": 0, "current_task": "10"}
        epic.dispatch_chain_upsert(test_db, "42", "wt1", data)
        result = epic.dispatch_chain_advance(test_db, "42", "wt1")
        assert result == "1|20"

        result2 = epic.dispatch_chain_advance(test_db, "42", "wt1")
        assert result2 == "2|30"

    def test_advance_at_end_raises(self, test_db):
        data = {"queue": [10], "current_index": 0, "current_task": "10"}
        epic.dispatch_chain_upsert(test_db, "42", "wt1", data)
        with pytest.raises(IndexError, match="already at end"):
            epic.dispatch_chain_advance(test_db, "42", "wt1")

    def test_advance_not_found(self, test_db):
        with pytest.raises(LookupError, match="not found"):
            epic.dispatch_chain_advance(test_db, "42", "nonexist")

    def test_csv_queue_fallback(self, test_db):
        """Queue stored as CSV string instead of JSON array."""
        p = _p(test_db)
        test_db.execute(
            "INSERT INTO epic_dispatch_chains (epic_id, worktree, queue, current_index, current_task) "
            f"VALUES ({p}, {p}, {p}, {p}, {p})",
            ("42", "wt-csv", "10,20,30", 0, "10"),
        )
        test_db.commit()
        result = epic.dispatch_chain_advance(test_db, "42", "wt-csv")
        assert result == "1|20"


class TestProgressNotes:
    def test_insert_and_list(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        result = epic.progress_note_insert(test_db, "42", 1, 1, "First note", "abc123")
        assert "Inserted progress note" in result

        epic.progress_note_insert(test_db, "42", 1, 2, "Second note", "def456")

        unsynced = epic.progress_note_list_unsynced(test_db, "42")
        assert "First note" in unsynced
        assert "Second note" in unsynced

    def test_mark_synced(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        epic.progress_note_insert(test_db, "42", 1, 1, "Note to sync")
        epic.progress_note_mark_synced(test_db, "42", 1, 1)

        unsynced = epic.progress_note_list_unsynced(test_db, "42")
        assert "Note to sync" not in unsynced

    def test_upsert_semantics(self, test_db):
        """ON CONFLICT updates body and commit_hash."""
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        epic.progress_note_insert(test_db, "42", 1, 1, "Original", "aaa")
        epic.progress_note_insert(test_db, "42", 1, 1, "Updated", "bbb")

        count = test_db.execute(
            "SELECT COUNT(*) FROM epic_progress_notes WHERE epic_id='42' AND task_num=1 AND note_num=1"
        ).fetchone()[0]
        assert count == 1

        body = test_db.execute(
            "SELECT body FROM epic_progress_notes WHERE epic_id='42' AND task_num=1 AND note_num=1"
        ).fetchone()[0]
        assert body == "Updated"
