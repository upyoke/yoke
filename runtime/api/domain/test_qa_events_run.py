"""Tests for ``qa_events.emit_qa_run_event``.

Covers AC-9 (c) and the run-side best-effort discipline from AC-9 (d):
with and without ``verdict``, and graceful handling when ``emit_event``
or the fallback ``query_one`` raises.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import qa_events
from yoke_core.domain._qa_events_test_helpers import (
    Captured,
    insert_deployment_requirement,
    insert_epic_requirement,
    insert_item_requirement,
    make_conn,
    patch_emit_event,
    patch_emit_event_raising,
)


@pytest.fixture
def conn():
    c = make_conn()
    try:
        yield c
    finally:
        c.close()


# ---------------------------------------------------------------------------
# AC-9 (c): emit_qa_run_event
# ---------------------------------------------------------------------------

def test_emit_run_event_without_verdict(conn, monkeypatch):
    captured = Captured()
    patch_emit_event(monkeypatch, captured)
    insert_item_requirement(conn, req_id=1, item_id=42)

    qa_events.emit_qa_run_event(
        conn,
        db_path=None,
        event_name="QARunRecorded",
        run_id=99,
        requirement_id=1,
        qa_kind="implementation_review",
    )

    assert len(captured.calls) == 1
    call = captured.calls[0]
    assert call["event_name"] == "QARunRecorded"
    assert call["event_kind"] == "lifecycle"
    assert call["event_type"] == "qa_execution"
    assert call["source_type"] == "system"
    assert call["severity"] == "INFO"
    assert call["item_id"] == "42"
    assert call["task_num"] is None
    detail = call["context"]["detail"]
    assert detail == {
        "run_id": 99,
        "requirement_id": 1,
        "qa_kind": "implementation_review",
    }
    assert "verdict" not in detail


def test_emit_run_event_with_verdict(conn, monkeypatch):
    captured = Captured()
    patch_emit_event(monkeypatch, captured)
    insert_epic_requirement(conn, req_id=2, epic_id=100, task_num=3)

    qa_events.emit_qa_run_event(
        conn,
        db_path=None,
        event_name="QARunCompleted",
        run_id=101,
        requirement_id=2,
        qa_kind="implementation_review",
        verdict="pass",
    )

    call = captured.calls[0]
    assert call["item_id"] == "100"
    assert call["task_num"] == 3
    detail = call["context"]["detail"]
    assert detail["verdict"] == "pass"
    assert detail["run_id"] == 101
    assert detail["requirement_id"] == 2


def test_emit_run_event_for_deployment_target(conn, monkeypatch):
    captured = Captured()
    patch_emit_event(monkeypatch, captured)
    insert_deployment_requirement(conn, req_id=3, run_id="run-deploy-001")

    qa_events.emit_qa_run_event(
        conn,
        db_path=None,
        event_name="QARunCompleted",
        run_id=200,
        requirement_id=3,
        qa_kind="smoke",
        verdict="fail",
    )

    call = captured.calls[0]
    assert call["item_id"] == "run-deploy-001"
    assert call["task_num"] is None
    assert call["context"]["detail"]["verdict"] == "fail"


# ---------------------------------------------------------------------------
# AC-9 (d): best-effort discipline for emit_qa_run_event
# ---------------------------------------------------------------------------

def test_emit_run_event_swallows_exceptions(conn, monkeypatch):
    patch_emit_event_raising(monkeypatch, RuntimeError("boom"))
    insert_item_requirement(conn, req_id=1, item_id=42)

    # Must not raise.
    qa_events.emit_qa_run_event(
        conn,
        db_path=None,
        event_name="QARunRecorded",
        run_id=99,
        requirement_id=1,
        qa_kind="implementation_review",
    )


def test_emit_run_event_swallows_query_one_failure(conn, monkeypatch):
    captured = Captured()
    patch_emit_event(monkeypatch, captured)

    def _raise_query_one(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(qa_events, "query_one", _raise_query_one)

    qa_events.emit_qa_run_event(
        conn,
        db_path=None,
        event_name="QARunRecorded",
        run_id=99,
        requirement_id=1,
        qa_kind="implementation_review",
    )

    assert captured.calls == []
