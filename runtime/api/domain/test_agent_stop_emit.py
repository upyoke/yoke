"""agent_stop — stop-context, stop-reason, outcome, and emit coverage."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from yoke_core.domain.agent_stop import (
    StopContext,
    build_stop_event_context,
    determine_stop_outcome,
    emit_harness_session_stopped,
    resolve_stop_reason,
)


class TestBuildStopEventContext:
    def test_context_is_valid_json(self):
        ctx = StopContext(
            item_id="1",
            task_num="2",
            final_status="implementing",
            auto_committed=True,
        )
        payload = json.loads(build_stop_event_context(ctx))
        assert payload == {
            "hook": "agent_stop",
            "auto_committed": True,
            "stop_reason": "auto_committed",
            "final_status": "implementing",
        }

    def test_empty_context_omits_optional_fields(self):
        payload = json.loads(build_stop_event_context(StopContext()))
        assert payload == {
            "hook": "agent_stop",
            "auto_committed": False,
            "stop_reason": "unexpected_stop",
        }

    def test_stop_reason_completed_for_terminal_status(self):
        ctx = StopContext(final_status="done")
        payload = json.loads(build_stop_event_context(ctx))
        assert payload["stop_reason"] == "completed"

    def test_stop_reason_auto_committed(self):
        ctx = StopContext(auto_committed=True, final_status="implementing")
        payload = json.loads(build_stop_event_context(ctx))
        assert payload["stop_reason"] == "auto_committed"


class TestResolveStopReason:
    def test_completed_for_done(self):
        ctx = StopContext(final_status="done")
        assert resolve_stop_reason(ctx) == "completed"

    def test_completed_for_reviewed_implementation(self):
        ctx = StopContext(final_status="reviewed-implementation")
        assert resolve_stop_reason(ctx) == "completed"

    def test_auto_committed(self):
        ctx = StopContext(auto_committed=True, final_status="implementing")
        assert resolve_stop_reason(ctx) == "auto_committed"

    def test_unexpected_stop_default(self):
        ctx = StopContext(final_status="implementing")
        assert resolve_stop_reason(ctx) == "unexpected_stop"

    def test_unexpected_stop_empty(self):
        ctx = StopContext()
        assert resolve_stop_reason(ctx) == "unexpected_stop"

    def test_completed_takes_priority_over_auto_committed(self):
        """Terminal status is the strongest signal — even if auto_committed is set."""
        ctx = StopContext(final_status="done", auto_committed=True)
        assert resolve_stop_reason(ctx) == "completed"


class TestDetermineStopOutcome:
    def test_done_returns_completed(self):
        assert determine_stop_outcome("done") == "completed"

    def test_reviewed_returns_completed(self):
        assert determine_stop_outcome("reviewed-implementation") == "completed"

    def test_implementing_returns_stopped(self):
        assert determine_stop_outcome("implementing") == "stopped"

    def test_empty_returns_stopped(self):
        assert determine_stop_outcome("") == "stopped"

    def test_unknown_returns_stopped(self):
        assert determine_stop_outcome("weird-status") == "stopped"


class TestEmitHarnessSessionStopped:
    """agent_stop.emit_harness_session_stopped calls
    yoke_core.domain.events.emit_event directly. Tests patch the native
    emitter and assert on kwargs.
    """

    def test_swallows_native_emitter_failure(self, tmp_path: Path):
        ctx = StopContext(item_id="1", task_num="1", final_status="done")
        with patch(
            "yoke_core.domain.events.emit_event",
            side_effect=RuntimeError("boom"),
        ):
            emit_harness_session_stopped(str(tmp_path), "sess-1", ctx)

    def test_emit_includes_item_and_task_ids(self, tmp_path: Path):
        ctx = StopContext(
            item_id="1",
            task_num="2",
            final_status="implementing",
            auto_committed=True,
        )
        with patch("yoke_core.domain.events.emit_event") as mock_emit:
            emit_harness_session_stopped(str(tmp_path), "sess-1", ctx)

        mock_emit.assert_called_once()
        args, kwargs = mock_emit.call_args
        assert args[0] == "HarnessSessionStopped"
        assert kwargs["item_id"] == "1"
        assert kwargs["task_num"] == 2
        assert kwargs["outcome"] == "stopped"
        assert kwargs["session_id"] == "sess-1"

    def test_emit_uses_completed_outcome_for_done(self, tmp_path: Path):
        ctx = StopContext(item_id="1", task_num="2", final_status="done")
        with patch("yoke_core.domain.events.emit_event") as mock_emit:
            emit_harness_session_stopped(str(tmp_path), "sess-1", ctx)
        mock_emit.assert_called_once()
        assert mock_emit.call_args.kwargs["outcome"] == "completed"

    def test_emit_includes_item_id_without_task_number(self, tmp_path: Path):
        ctx = StopContext(item_id="42", auto_committed=True)
        with patch("yoke_core.domain.events.emit_event") as mock_emit:
            emit_harness_session_stopped(str(tmp_path), "sess-1", ctx)
        mock_emit.assert_called_once()
        kwargs = mock_emit.call_args.kwargs
        assert kwargs["item_id"] == "42"
        assert "task_num" not in kwargs

    def test_emit_omits_non_numeric_task_number(self, tmp_path: Path):
        ctx = StopContext(item_id="42", task_num="alpha")
        with patch("yoke_core.domain.events.emit_event") as mock_emit:
            emit_harness_session_stopped(str(tmp_path), "sess-1", ctx)
        mock_emit.assert_called_once()
        kwargs = mock_emit.call_args.kwargs
        assert kwargs["item_id"] == "42"
        assert "task_num" not in kwargs

    def test_emit_passes_session_id(self, tmp_path: Path):
        ctx = StopContext(item_id="1")
        with patch("yoke_core.domain.events.emit_event") as mock_emit:
            emit_harness_session_stopped(str(tmp_path), "canonical-sess-xyz", ctx)
        mock_emit.assert_called_once()
        assert mock_emit.call_args.kwargs["session_id"] == "canonical-sess-xyz"
