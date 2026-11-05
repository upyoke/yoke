"""Dispatch chains and progress notes for ``yoke_core.domain.epic``.

Split from ``test_epic_full.py``.

Uses the shared ``test_db`` fixture from ``conftest.py``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import epic
from runtime.api.conftest import insert_item

TEST_EPIC_ID = 42
TEST_EPIC_REF = f"YOK-{TEST_EPIC_ID}"
TEST_EPIC_WORKTREE_PATH = f"/tmp/worktrees/{TEST_EPIC_REF}"






class TestDispatchChains:
    @pytest.fixture(autouse=True)
    def _seed_parent_item(self, test_db):
        insert_item(
            test_db,
            id=TEST_EPIC_ID,
            workflow_id="epic",
            status="planned",
            project="yoke",
        )


    def test_update_not_found(self, test_db):
        with pytest.raises(LookupError, match="not found"):
            epic.dispatch_chain_update(test_db, "42", "nonexist", "current_task", "1")


    def test_list_empty(self, test_db):
        result = epic.dispatch_chain_list(test_db, "42")
        assert result == ""


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
