"""Tests for the ``workflow_item.epic_progress_note.append`` handler."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.api.domain.workflow_item_update_test_support import (
    add_epic_task as _add_task,
    retained_connection as _conn_cm,
    seed_workflow_item_connection as _seed_conn,
    workflow_item_request as _build_request,
)
from yoke_core.domain.handlers import (
    workflow_item_epic_progress_note as progress_handler,
)


class TestProgressNoteAppendHandler(unittest.TestCase):
    def test_inserts_row(self):
        conn = _seed_conn()
        _add_task(conn, 100, 1, "first")
        request = _build_request(
            "workflow_item.epic_progress_note.append",
            payload={
                "note_num": 1,
                "body": "first note",
                "commit_hash": "abc1234",
            },
        )
        with patch.object(
            progress_handler,
            "_open_connection",
            lambda: _conn_cm(conn),
        ):
            with patch.object(
                progress_handler.epic,
                "progress_note_insert",
                side_effect=lambda c, e, t, n, b, h="": (
                    c.execute(
                        "INSERT INTO epic_progress_notes "
                        "(epic_id, task_num, note_num, body, commit_hash, "
                        "created_at) VALUES "
                        "(%s, %s, %s, %s, %s, '2026-01-01T00:00:00Z')",
                        (str(e), t, n, b, h),
                    )
                    or "ok"
                ),
            ):
                outcome = progress_handler.handle_append(request)
        assert outcome.primary_success is True
        assert outcome.result_payload["note_num"] == 1
        rows = conn.execute(
            "SELECT note_num, commit_hash FROM epic_progress_notes "
            "WHERE epic_id='100' AND task_num=1"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["commit_hash"] == "abc1234"

    def test_not_found(self):
        conn = _seed_conn()
        request = _build_request(
            "workflow_item.epic_progress_note.append",
            task_num=99,
            payload={"note_num": 1, "body": "x"},
        )
        with patch.object(
            progress_handler,
            "_open_connection",
            lambda: _conn_cm(conn),
        ):
            outcome = progress_handler.handle_append(request)
        assert outcome.error.code == "target_not_found"

    def test_invalid_note_num(self):
        conn = _seed_conn()
        _add_task(conn, 100, 1, "first")
        request = _build_request(
            "workflow_item.epic_progress_note.append",
            payload={"note_num": 0, "body": "x"},
        )
        with patch.object(
            progress_handler,
            "_open_connection",
            lambda: _conn_cm(conn),
        ):
            outcome = progress_handler.handle_append(request)
        assert outcome.error.code == "invalid_payload"


if __name__ == "__main__":
    unittest.main()
