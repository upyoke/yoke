# ruff: noqa: F811
"""Codex runtime-id and post-decision telemetry tests.
Split from ``test_sessions_queries.py``. Covers Codex runtime_session_id
plumbing into offer envelopes plus the post-decision telemetry surface.
"""

from __future__ import annotations

import json
import os

from unittest.mock import patch

from runtime.api.test_sessions import (
    conn,  # noqa: F401 — fixture import
    ownership_conn,  # noqa: F401 — fixture import
    _ensure_active_session,
)
from yoke_core.domain.sessions import (
    emit_post_decision_telemetry,
    session_offer_with_ownership,
)


class TestSessionOfferRuntimeId:
    """Codex runtime_session_id plumbing into the offer envelope."""

    def test_codex_offer_stores_runtime_session_id(self, ownership_conn):
        """AC-8: Codex offers persist runtime_session_id in offer_envelope."""
        conn, ws = ownership_conn
        _ensure_active_session(
            conn,
            "codex-2026-offer",
            ws,
            executor="codex",
            provider="openai",
            model="gpt-5.4",
            execution_lane="ALTMAN",
        )
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "019d62e0-2c92-7a03-8d99-b18206cfa7e7"}):
            session_offer_with_ownership(
                conn,
                session_id="codex-2026-offer",
                executor="codex",
                provider="openai",
                model="gpt-5.4",
                workspace=ws,
            )
        row = conn.execute(
            "SELECT offer_envelope FROM harness_sessions WHERE session_id = 'codex-2026-offer'"
        ).fetchone()
        assert row is not None
        envelope = json.loads(row["offer_envelope"])
        assert envelope.get("runtime_session_id") == "019d62e0-2c92-7a03-8d99-b18206cfa7e7"

    def test_claude_offer_omits_runtime_session_id(self, ownership_conn):
        """AC-8: Claude Code offers do NOT include runtime_session_id."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "claude-no-runtime", ws, model="opus")
        with patch.dict(os.environ, {}, clear=False):
            # Ensure CODEX_THREAD_ID is not set
            os.environ.pop("CODEX_THREAD_ID", None)
            session_offer_with_ownership(
                conn,
                session_id="claude-no-runtime",
                executor="claude-code",
                provider="anthropic",
                model="opus",
                workspace=ws,
            )
        row = conn.execute(
            "SELECT offer_envelope FROM harness_sessions WHERE session_id = 'claude-no-runtime'"
        ).fetchone()
        assert row is not None
        envelope = json.loads(row["offer_envelope"])
        assert "runtime_session_id" not in envelope


class TestPostDecisionTelemetry:
    @patch("yoke_core.domain.sessions_analytics.emit_lane_routing_decision")
    @patch("yoke_core.domain.sessions_analytics.emit_adapter_dispatch_chosen")
    def test_resume_resolves_dispatch_from_current_item_state(
        self,
        mock_dispatch,
        mock_lane,
        ownership_conn,
    ):
        conn, _ws = ownership_conn
        conn.execute(
            """UPDATE items
               SET status = 'refined-idea',
                   type = 'issue',
                   project_id = 2
               WHERE id = 100"""
        )
        conn.commit()

        emit_post_decision_telemetry(
            conn,
            "sess-telemetry",
            action="resume",
            reason="Resume claimed work",
            actual_lane="DARIUS",
            project="externalwebapp",
            context={
                "item_id": "YOK-100",
                "status": "refined-idea",
            },
        )

        mock_lane.assert_called_once()
        lane_kwargs = mock_lane.call_args.kwargs
        assert lane_kwargs["project"] == "externalwebapp"

        mock_dispatch.assert_called_once()
        dispatch_kwargs = mock_dispatch.call_args.kwargs
        assert dispatch_kwargs["project"] == "externalwebapp"
        assert dispatch_kwargs["adapter"] == "advance"
        assert dispatch_kwargs["dispatch_source"] == "resume-status-mapping"
        assert dispatch_kwargs["actual_lane"] == "DARIUS"

    @patch("yoke_core.domain.sessions_analytics.emit_lane_routing_decision")
    @patch("yoke_core.domain.sessions_analytics.emit_adapter_dispatch_chosen")
    def test_lane_policy_wait_emits_blocked_policy_telemetry(
        self,
        mock_dispatch,
        mock_lane,
        ownership_conn,
    ):
        conn, _ws = ownership_conn

        emit_post_decision_telemetry(
            conn,
            "sess-lane-block",
            action="wait",
            reason="Lane policy blocks this path",
            actual_lane="ALTMAN",
            project="yoke",
            context={
                "selected_item": "YOK-100",
                "wait_reason": "lane_policy_disallows_path",
                "required_path": "advance",
                "allowed_paths": ["refine", "polish"],
                "scheduler": {
                    "next_step": "advance",
                },
            },
        )

        mock_lane.assert_called_once()
        lane_kwargs = mock_lane.call_args.kwargs
        assert lane_kwargs["decision"] == "blocked_policy"
        assert lane_kwargs["actual_lane"] == "ALTMAN"
        assert lane_kwargs["context"]["required_path"] == "advance"
        assert lane_kwargs["context"]["allowed_paths"] == ["refine", "polish"]
        mock_dispatch.assert_called_once()

    @patch("yoke_core.domain.sessions_analytics.emit_lane_routing_decision")
    @patch("yoke_core.domain.sessions_analytics.emit_adapter_dispatch_chosen")
    def test_unknown_lane_wait_emits_blocked_policy_telemetry(
        self,
        mock_dispatch,
        mock_lane,
        ownership_conn,
    ):
        conn, _ws = ownership_conn

        emit_post_decision_telemetry(
            conn,
            "sess-lane-unknown",
            action="wait",
            reason="Lane policy does not know this lane",
            actual_lane="primary",
            project="yoke",
            context={
                "selected_item": "YOK-100",
                "wait_reason": "lane_policy_unknown",
                "required_path": "polish",
                "unknown_lane": "PRIMARY",
                "configured_lanes": ["ALTMAN", "DARIUS"],
                "scheduler": {
                    "next_step": "polish",
                },
            },
        )

        mock_lane.assert_called_once()
        lane_kwargs = mock_lane.call_args.kwargs
        assert lane_kwargs["decision"] == "blocked_policy"
        assert lane_kwargs["context"]["wait_reason"] == "lane_policy_unknown"
        assert lane_kwargs["context"]["unknown_lane"] == "PRIMARY"
        assert lane_kwargs["context"]["configured_lanes"] == ["ALTMAN", "DARIUS"]
        mock_dispatch.assert_called_once()
