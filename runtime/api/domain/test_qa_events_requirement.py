"""Tests for ``qa_events.emit_qa_requirement_event``.

Covers AC-9 (b) and the requirement-side best-effort discipline from
AC-9 (d): with and without ``extra_detail``, with and without
``target_row``, and graceful handling when ``emit_event`` or the
fallback ``query_one`` raises.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import qa_events
from yoke_core.domain._qa_events_test_helpers import (
    Captured,
    fetch_row,
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
# AC-9 (b): emit_qa_requirement_event
# ---------------------------------------------------------------------------

def test_emit_requirement_event_with_target_row_skips_lookup(conn, monkeypatch):
    captured = Captured()
    patch_emit_event(monkeypatch, captured)
    insert_item_requirement(conn, req_id=1, item_id=42)
    row = fetch_row(conn, 1)

    qa_events.emit_qa_requirement_event(
        conn,
        db_path=None,
        event_name="QARequirementCreated",
        requirement_id=1,
        qa_kind="implementation_review",
        qa_phase="verification",
        target_row=row,
    )

    assert len(captured.calls) == 1
    call = captured.calls[0]
    assert call["event_name"] == "QARequirementCreated"
    assert call["event_kind"] == "lifecycle"
    assert call["event_type"] == "qa_lifecycle"
    assert call["source_type"] == "system"
    assert call["severity"] == "INFO"
    assert call["item_id"] == "42"
    assert call["task_num"] is None
    detail = call["context"]["detail"]
    assert detail == {
        "requirement_id": 1,
        "qa_kind": "implementation_review",
        "qa_phase": "verification",
    }


def test_emit_requirement_event_without_target_row_queries_db(conn, monkeypatch):
    captured = Captured()
    patch_emit_event(monkeypatch, captured)
    insert_epic_requirement(conn, req_id=2, epic_id=100, task_num=3)

    qa_events.emit_qa_requirement_event(
        conn,
        db_path=None,
        event_name="QARequirementUpdated",
        requirement_id=2,
        qa_kind="implementation_review",
        qa_phase="verification",
    )

    assert len(captured.calls) == 1
    call = captured.calls[0]
    assert call["item_id"] == "100"
    assert call["task_num"] == 3


def test_emit_requirement_event_with_extra_detail(conn, monkeypatch):
    """``extra_detail`` is merged after rationale/source so callers can extend."""
    captured = Captured()
    patch_emit_event(monkeypatch, captured)
    insert_item_requirement(conn, req_id=1, item_id=42)
    row = fetch_row(conn, 1)

    qa_events.emit_qa_requirement_event(
        conn,
        db_path=None,
        event_name="QARequirementCreated",
        requirement_id=1,
        qa_kind="implementation_review",
        qa_phase="verification",
        rationale="seeded by flow",
        source="flow_derived",
        target_row=row,
        extra_detail={"flow_id": "flow-abc", "stage": "smoke"},
    )

    detail = captured.calls[0]["context"]["detail"]
    assert detail["requirement_id"] == 1
    assert detail["qa_kind"] == "implementation_review"
    assert detail["qa_phase"] == "verification"
    assert detail["rationale"] == "seeded by flow"
    assert detail["source"] == "flow_derived"
    assert detail["flow_id"] == "flow-abc"
    assert detail["stage"] == "smoke"


def test_emit_requirement_event_without_extra_detail(conn, monkeypatch):
    """When extra_detail is None or empty, detail keys are exactly the base set."""
    captured = Captured()
    patch_emit_event(monkeypatch, captured)
    insert_item_requirement(conn, req_id=1, item_id=42)
    row = fetch_row(conn, 1)

    qa_events.emit_qa_requirement_event(
        conn,
        db_path=None,
        event_name="QARequirementWaived",
        requirement_id=1,
        qa_kind="implementation_review",
        qa_phase="verification",
        rationale="operator waived",
        source="operator",
        target_row=row,
        extra_detail=None,
    )

    detail = captured.calls[0]["context"]["detail"]
    assert set(detail.keys()) == {"requirement_id", "qa_kind", "qa_phase", "rationale", "source"}


def test_emit_requirement_event_extra_detail_overrides_base_keys(conn, monkeypatch):
    """``extra_detail`` is merged last, so it can override base detail keys.

    This documents the canonical merge order: extra_detail wins. Callers
    that want this behavior rely on it; callers that don't simply pick a
    non-overlapping key namespace.
    """
    captured = Captured()
    patch_emit_event(monkeypatch, captured)
    insert_item_requirement(conn, req_id=1, item_id=42)
    row = fetch_row(conn, 1)

    qa_events.emit_qa_requirement_event(
        conn,
        db_path=None,
        event_name="QARequirementCreated",
        requirement_id=1,
        qa_kind="implementation_review",
        qa_phase="verification",
        target_row=row,
        extra_detail={"qa_phase": "post_deploy"},
    )

    detail = captured.calls[0]["context"]["detail"]
    assert detail["qa_phase"] == "post_deploy"


def test_emit_requirement_event_deployment_target(conn, monkeypatch):
    captured = Captured()
    patch_emit_event(monkeypatch, captured)
    insert_deployment_requirement(conn, req_id=3, run_id="run-deploy-001")

    qa_events.emit_qa_requirement_event(
        conn,
        db_path=None,
        event_name="QARequirementCreated",
        requirement_id=3,
        qa_kind="smoke",
        qa_phase="post_deploy",
    )

    call = captured.calls[0]
    assert call["item_id"] == "run-deploy-001"
    assert call["task_num"] is None


# ---------------------------------------------------------------------------
# AC-9 (d): best-effort discipline for emit_qa_requirement_event
# ---------------------------------------------------------------------------

def test_emit_requirement_event_swallows_exceptions(conn, monkeypatch):
    patch_emit_event_raising(monkeypatch, RuntimeError("boom"))
    insert_item_requirement(conn, req_id=1, item_id=42)

    # Must not raise.
    qa_events.emit_qa_requirement_event(
        conn,
        db_path=None,
        event_name="QARequirementCreated",
        requirement_id=1,
        qa_kind="implementation_review",
        qa_phase="verification",
    )


def test_emit_requirement_event_swallows_query_one_failure(conn, monkeypatch):
    """If the fallback ``query_one`` call fails, the helper must return cleanly."""
    captured = Captured()
    patch_emit_event(monkeypatch, captured)

    def _raise_query_one(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(qa_events, "query_one", _raise_query_one)

    qa_events.emit_qa_requirement_event(
        conn,
        db_path=None,
        event_name="QARequirementCreated",
        requirement_id=1,
        qa_kind="implementation_review",
        qa_phase="verification",
    )

    # The helper returned cleanly without emitting.
    assert captured.calls == []
