"""Latency metadata coverage for append-style operator notes."""

from __future__ import annotations

import io
from unittest.mock import Mock, patch

from yoke_core.domain import backlog_structured_write_op as _structured
from yoke_core.domain import item_field_transform_sync as _sync
from yoke_core.domain.handlers import items_progress_log as _progress
from yoke_core.domain.item_field_transform import TransformResult
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _progress_request() -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.progress_log.append",
        actor=ActorContext(session_id="s", actor_id="agent"),
        target=TargetRef(kind="item", item_id=1903),
        payload={"headline": "checkpoint", "content": "body"},
    )


def test_progress_log_append_response_surfaces_sync_metadata(monkeypatch):
    result = TransformResult(
        success=True,
        operation="section-append",
        item_id=1903,
        section="Progress Log",
        changed=True,
        old_line_count=1,
        new_line_count=4,
        verification="ok",
        body_sync_mode="ok",
        body_sync_elapsed_ms=123,
    )
    monkeypatch.setattr(
        _progress.item_field_transform, "section_append", lambda **_: result,
    )

    outcome = _progress.handle_append(_progress_request())

    assert outcome.primary_success is True
    assert outcome.result_payload["github_sync"] == "ok"
    assert outcome.result_payload["body_sync_mode"] == "ok"
    assert outcome.result_payload["body_sync_elapsed_ms"] == 123


def test_section_sync_helper_reports_elapsed_degraded_ms(monkeypatch):
    ticks = iter([10.0, 10.125])
    monkeypatch.setattr(_sync, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(
        _sync._sections,
        "sync_body_after_section_mutation",
        lambda item_id, operation: (False, "section append: sync_body failed"),
    )

    ok, reason, mode, elapsed_ms = _sync.sync_section_body(1903, "append")

    assert ok is False
    assert reason == "section append: sync_body failed"
    assert mode == "degraded"
    assert elapsed_ms == 125


def test_structured_write_skips_body_sync_when_content_unchanged(monkeypatch):
    fake_conn = Mock()
    fake_conn.close = Mock()
    monkeypatch.setattr(_structured, "_resolve_write_db_path", lambda: "db")
    monkeypatch.setattr(_structured, "_assert_write_db_ready", lambda db: None)
    monkeypatch.setattr(_structured, "connect", lambda db: fake_conn)
    monkeypatch.setattr(
        _structured, "_query_item_field", lambda conn, item_id, field: "same\n",
    )

    with patch.object(_structured._rendering, "_render_body") as render_body, \
            patch.object(_structured._rendering, "_sync_body") as sync_body, \
            patch.object(_structured._rendering, "_maybe_rebuild_board") as rebuild:
        result = _structured.execute_structured_write(
            item_id=1903,
            field="spec",
            content="same\n",
            out=io.StringIO(),
        )

    assert result == {
        "success": True,
        "changed": False,
        "body_sync_mode": "skipped_no_change",
        "body_budget_degraded": False,
        "body_sync_elapsed_ms": 0,
    }
    fake_conn.execute.assert_not_called()
    fake_conn.commit.assert_not_called()
    fake_conn.close.assert_called_once()
    render_body.assert_not_called()
    sync_body.assert_not_called()
    rebuild.assert_not_called()
