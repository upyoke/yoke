"""Full server capture keeps parser diagnostics, identity and durable failures."""

from contextlib import nullcontext
from unittest.mock import patch

import pytest

from runtime.api.domain.reflection_capture_test_support import make_reflection_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.reflection_capture import handle_capture


def response_text(body="Useful observation."):
    return (
        "Agent response\n---REFLECTION-START---\n---BEGIN ENTRY---\n"
        "timestamp: 2026-10-15T12:00:00Z\nagent: engineer\n"
        f"category: friction\n{body}\n---END ENTRY---\n---REFLECTION-END---"
    )


def request(text):
    return FunctionCallRequest(
        function="ouroboros.reflection.capture",
        actor=ActorContext(session_id="capturing-session"),
        target=TargetRef(kind="global", project_id="yoke"),
        payload={"text": text, "default_agent": "engineer"},
    )


@pytest.fixture
def conn():
    connection = make_reflection_db()
    yield connection
    connection.close()


def test_capture_and_duplicate_keep_full_counts(conn):
    with patch(
        "yoke_core.domain.db_helpers.connect", side_effect=lambda: nullcontext(conn)
    ):
        first = handle_capture(request(response_text()))
        second = handle_capture(request(response_text()))
    assert first.primary_success, first.error
    assert first.result_payload["blocks_seen"] == 1
    assert first.result_payload["entries_persisted"] == 1
    assert second.primary_success, second.error
    assert second.result_payload["entries_duplicate_skipped"] == 1
    assert second.result_payload["entries_persisted"] == 0
    row = conn.execute(
        "SELECT agent, body, project_id FROM ouroboros_entries"
    ).fetchone()
    assert tuple(row) == ("engineer", "Useful observation.", 1)


def test_marker_dispatch_carries_capturing_session_project_and_stable_identity(conn):
    text = response_text("field_note_kind: failed\nA taught command refused.")
    calls = []

    def dispatch(req, **kwargs):
        from yoke_contracts.api.function_call import FunctionCallResponse

        calls.append(req)
        return FunctionCallResponse(
            success=True,
            function=req.function,
            request_id=req.request_id,
            version="v1",
            result={"entry_id": "1"},
        )

    with (
        patch(
            "yoke_core.domain.db_helpers.connect", side_effect=lambda: nullcontext(conn)
        ),
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=dispatch,
        ),
        patch("yoke_core.domain.handlers.__init_register__.register_all_handlers"),
    ):
        assert handle_capture(request(text)).primary_success
        assert handle_capture(request(text)).primary_success
    assert len(calls) == 2
    assert calls[0].actor.session_id == "capturing-session"
    assert calls[0].payload["project"] == "yoke"
    assert calls[0].payload["actor_role"] == "engineer"
    assert calls[0].request_id == calls[1].request_id


def test_partial_and_malformed_counts_are_returned_as_incomplete(conn):
    text = "---REFLECTION-START---\n"
    with patch(
        "yoke_core.domain.db_helpers.connect", side_effect=lambda: nullcontext(conn)
    ):
        outcome = handle_capture(request(text))
    # An empty block is deliberately classified as a known false positive.
    assert outcome.primary_success
    assert outcome.result_payload["blocks_skipped_known_falsepositive"] == 1
    malformed = response_text().replace("category: friction\n", "")
    with patch(
        "yoke_core.domain.db_helpers.connect", side_effect=lambda: nullcontext(conn)
    ):
        outcome = handle_capture(request(malformed))
    assert not outcome.primary_success
    assert outcome.error.code == "reflection_capture_incomplete"
    assert outcome.result_payload["errors"]


def test_persistence_failure_never_reports_success(conn):
    with (
        patch(
            "yoke_core.domain.db_helpers.connect", side_effect=lambda: nullcontext(conn)
        ),
        patch(
            "yoke_core.domain.ouroboros.cmd_insert_entry",
            side_effect=RuntimeError("unavailable"),
        ),
    ):
        outcome = handle_capture(request(response_text()))
    assert not outcome.primary_success
    assert outcome.error.code == "reflection_capture_incomplete"
    assert outcome.result_payload["entries_persist_failed"] == 1
    assert outcome.result_payload["entries_persisted"] == 0
    assert "rerun" in outcome.error.recovery_hint
