"""Dash close-out leaves the terminal outcome in the Progress Log."""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.dash_execution import record_dash_evidence
from yoke_core.domain.progress_log import PROGRESS_LOG_SECTION


MERGE_SHA = "b" * 40


def _ensure_item_sections(test_db) -> None:
    test_db.execute(
        "CREATE TABLE IF NOT EXISTS item_sections ("
        "item_id INTEGER NOT NULL REFERENCES items(id), "
        "section_name TEXT NOT NULL, content TEXT NOT NULL, "
        "ordering INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "PRIMARY KEY(item_id, section_name))"
    )
    test_db.commit()


def _record_close_out(test_db) -> None:
    record_dash_evidence(
        test_db,
        item_id=2144,
        result_summary="Closed successfully after operator escalation.",
        verification_summary="Focused regression passed.",
        verification_status="passed",
        commit_sha="a" * 40,
        merge_sha=MERGE_SHA,
        touched_files=["src/close_out.py"],
        tree_root="/repo/.worktrees/lane",
        tree_head_sha="a" * 40,
    )


def test_close_out_appends_landing_outcome_after_escalation(test_db):
    _ensure_item_sections(test_db)
    insert_item(
        test_db,
        id=2144,
        workflow_id="dash",
        status="reviewing-implementation",
    )
    prior = (
        "## 2026-08-13T12:00:00Z entry — Escalated\n"
        "Waiting for operator input.\n"
    )
    test_db.execute(
        "INSERT INTO item_sections "
        "(item_id, section_name, content, ordering, source, created_at, updated_at) "
        "VALUES (%s, %s, %s, 200, 'operator', %s, %s)",
        (
            2144,
            PROGRESS_LOG_SECTION,
            prior,
            "2026-08-13T12:00:00Z",
            "2026-08-13T12:00:00Z",
        ),
    )
    test_db.commit()

    _record_close_out(test_db)
    test_db.execute("UPDATE items SET status = 'done' WHERE id = %s", (2144,))
    test_db.commit()

    content = test_db.execute(
        "SELECT content FROM item_sections "
        "WHERE item_id = %s AND section_name = %s",
        (2144, PROGRESS_LOG_SECTION),
    ).fetchone()[0]
    assert content.startswith(prior)
    assert "entry — Landed" in content
    assert "Closed successfully after operator escalation." in content
    assert f"Merge SHA: `{MERGE_SHA}`" in content


def test_close_out_retry_does_not_duplicate_landing_entry(test_db):
    _ensure_item_sections(test_db)
    insert_item(test_db, id=2144, workflow_id="dash")

    _record_close_out(test_db)
    _record_close_out(test_db)

    content = test_db.execute(
        "SELECT content FROM item_sections "
        "WHERE item_id = %s AND section_name = %s",
        (2144, PROGRESS_LOG_SECTION),
    ).fetchone()[0]
    assert content.count(f"Merge SHA: `{MERGE_SHA}`") == 1
