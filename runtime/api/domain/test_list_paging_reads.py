"""Handler paging retains ordered identities and multiline note bodies."""

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.handlers import (
    qa_reads,
    workflow_item_epic_progress_note as notes,
)
from yoke_core.domain.qa_activity_selection import select_activity


def request(function, target, payload):
    return FunctionCallRequest.model_validate(
        {
            "function": function,
            "version": "v1",
            "request_id": "paging-test",
            "actor": {"session_id": "test-session"},
            "target": target,
            "payload": payload,
        }
    )


def test_requirement_pages_keep_currency_and_do_not_skip_rows():
    rows = [{"id": number} for number in range(61)]
    conn = MagicMock()
    seen = []
    with (
        patch("yoke_core.domain.db_helpers.connect", return_value=conn),
        patch("yoke_core.domain.db_helpers.query_rows", return_value=rows),
        patch.object(qa_reads, "REQ_COLUMNS", ("id",)),
        patch.object(
            qa_reads,
            "annotate_requirement_currency",
            side_effect=lambda conn, rows: rows,
        ),
    ):
        for offset in (0, 25, 50):
            outcome = qa_reads.handle_qa_requirement_list(
                request(
                    "qa.requirement.list",
                    {"kind": "item", "item_id": 1},
                    {"limit": 25, "offset": offset},
                )
            )
            assert outcome.primary_success
            page = outcome.result_payload
            seen.extend(row["id"] for row in page["rows"])
            assert page["next_offset"] == (offset + 25 if offset < 50 else None)
    assert seen == list(range(61))


def test_notes_page_preserves_multiline_and_pipe_characters():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {"exists": 1}
    body = "First | column\nSecond line\n" + "界" * 10000
    rows = [
        {"id": number, "note_num": 61 - number, "body": body} for number in range(61)
    ]
    with (
        patch.object(notes, "_open_connection", return_value=nullcontext(conn)),
        patch("yoke_core.domain.db_helpers.query_rows", return_value=rows),
    ):
        outcome = notes.handle_list(
            request(
                "workflow_item.epic_progress_note.list",
                {"kind": "epic_task", "epic_id": 1, "task_num": 1},
                {"limit": 4, "offset": 4},
            )
        )
    assert outcome.primary_success
    result = outcome.result_payload
    assert [row["id"] for row in result["rows"]] == [4, 5, 6, 7]
    assert result["rows"][0]["body"] == body
    assert result["next_offset"] == 8
    assert "body" not in result


def test_activity_sql_applies_offset_before_hydrating_rows():
    conn = MagicMock()
    with patch(
        "yoke_core.domain.qa_activity_selection.query_rows", return_value=[]
    ) as query:
        rows, selection = select_activity(
            conn,
            "%s",
            "WHERE pr.id=%s",
            [3],
            bounded=4,
            item_scoped=False,
            per_run_group=False,
            offset=12,
        )
    assert rows == []
    assert selection is None
    sql, params = query.call_args.args[1:]
    assert sql.endswith("LIMIT %s OFFSET %s")
    assert params == (3, 4, 12)
