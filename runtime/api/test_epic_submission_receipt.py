"""Submission receipt lookup from epic progress notes."""

from __future__ import annotations

import pytest

from runtime.api.conftest import insert_epic_task, insert_item
from yoke_core.domain import epic


RECEIPT = """Progress note text.

---SUBMISSION-CHECKS-START---
test_plan: PASS - pytest passed
files_touched: PASS - checked files
edited_tests: SKIP - no tests edited
clean_worktree: PASS - git status --porcelain is empty
progress_notes: PASS - note written
file_budget: PASS - files under limit
---SUBMISSION-CHECKS-END---
"""


def test_submission_receipt_get_reads_latest_progress_note(test_db):
    db = test_db
    insert_item(db, id=42, project_sequence=7)
    insert_epic_task(db, epic_id=42, task_num=1, title="Task")
    epic.progress_note_insert(db, "42", 1, 1, "ordinary note", "aaa")
    epic.progress_note_insert(db, "42", 1, 2, RECEIPT, "bbb")

    result = epic.submission_receipt_get(db, "42", 1, after_note_count=1)

    assert result.startswith("PASS|YOK-7|1|2|bbb|")
    assert "clean_worktree=PASS - git status --porcelain is empty" in result


def test_submission_receipt_get_fails_without_new_receipt(test_db):
    db = test_db
    insert_item(db, id=42, project_sequence=7)
    insert_epic_task(db, epic_id=42, task_num=1, title="Task")
    epic.progress_note_insert(db, "42", 1, 1, RECEIPT, "aaa")

    with pytest.raises(LookupError, match="no submission receipt"):
        epic.submission_receipt_get(db, "42", 1, after_note_count=1)


def test_submission_receipt_get_rejects_bad_receipt(test_db):
    db = test_db
    bad = RECEIPT.replace("clean_worktree: PASS", "clean_worktree: FAIL")
    insert_item(db, id=42, project_sequence=7)
    insert_epic_task(db, epic_id=42, task_num=1, title="Task")
    epic.progress_note_insert(db, "42", 1, 1, bad, "aaa")

    with pytest.raises(ValueError, match="clean_worktree"):
        epic.submission_receipt_get(db, "42", 1)
