"""Question requester labels delegate to the shared session renderer."""

from runtime.api.domain.decision_request_requester_label_test_support import (
    add_holdings_schema as add_holdings_schema,
)

from unittest.mock import Mock

from yoke_core.domain import decision_request_requester_label as labels


def test_requesters_use_shared_session_labels(monkeypatch):
    conn = object()
    names = {"asking": "[PILLS] · claude-desktop · alpha · holds ALP-1 'Test work'"}
    read = Mock(return_value=names)
    monkeypatch.setattr(labels, "session_display_names", read)
    assert labels.requester_labels(conn, ["asking", "idle"]) == names
    read.assert_called_once_with(conn, ["asking", "idle"])


def test_question_page_reads_labels_once(monkeypatch):
    from runtime.api.domain.decision_request_operator_question_test_support import (
        conn as fixture,
        filing,
    )
    from yoke_core.domain.decision_request_question_filing import file_question
    from yoke_core.domain.decision_request_rows import request_rows

    generator = fixture.__wrapped__()
    conn = next(generator)
    try:
        ids = [
            file_question(
                conn,
                **filing(
                    requesting_session_id=session,
                    subject_key=f"{session}:{key}",
                ),
            )[0]["id"]
            for session, key in [
                ("worker", "one"),
                ("worker", "two"),
                ("other", "three"),
            ]
        ]
        read = Mock(
            return_value={
                "worker": "Worker chat · codex · alpha",
                "other": "Other chat · cursor · alpha",
            }
        )
        monkeypatch.setattr(labels, "requester_labels", read)
        rows = request_rows(conn, ids)
        read.assert_called_once()
        assert set(read.call_args.args[1]) == {"worker", "other"}
        assert len(rows) == 3
        assert rows[ids[0]]["requesting_session_label"] == "Worker chat · codex · alpha"
        assert rows[ids[2]]["requesting_session_label"] == "Other chat · cursor · alpha"
    finally:
        generator.close()


