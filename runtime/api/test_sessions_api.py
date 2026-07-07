"""Session API tests: CLI dispatch, events, stale reclaim, telemetry, release helpers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from unittest.mock import patch

from runtime.api.test_sessions import (
    _register,
    _REPO_ROOT,
    conn,
    ownership_conn,
    _ensure_active_session,
)
from runtime.api.test_dependency_schema import ITEMS_SCHEMA


_STALE_TS = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
    "%Y-%m-%dT%H:%M:%SZ"
)


from yoke_core.domain.sessions import (
    EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS,
    EVENT_HARNESS_SESSION_ENDED,
    EVENT_HARNESS_SESSION_STARTED,
    EVENT_HARNESS_SESSION_STALE_SWEEP_COMPLETED,
    EVENT_WORK_CLAIMED,
    EVENT_WORK_HANDED_OFF,
    EVENT_WORK_RECLAIMED,
    EVENT_WORK_RELEASED,
    SessionError,
    _emit_session_event,
    claim_work,
    clean_stale_harness_sessions,
    emit_next_action_chosen,
    end_session,
    handoff_claim,
    reclaim_stale_item_claims,
    reclaim_stale_session,
    register_session,
    release_claim,
    release_claims_for_done_item,
)


# ---------------------------------------------------------------------------
# Event emission tests
# ---------------------------------------------------------------------------


class TestEventEmission:
    """Verify that structured events are emitted for each lifecycle operation.

    Uses the module-level backend-aware ``conn`` fixture (imported from
    ``test_sessions``) so the reclaim path's ``now_sql``-derived SQL and the
    constraint-error re-raise match the active test backend.
    """

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_register_emits_event(self, mock_emit, conn):
        register_session(
            conn,
            session_id="ev-1",
            executor="agent",
            provider="anthropic",
            model="opus",
            workspace="/tmp/test",
            project_id=1,
        )
        mock_emit.assert_called_once()
        args, kwargs = mock_emit.call_args
        assert args[0] == EVENT_HARNESS_SESSION_STARTED
        assert kwargs["session_id"] == "ev-1"

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_claim_emits_event(self, mock_emit, conn):
        _register(conn, session_id="ev-2")
        mock_emit.reset_mock()
        claim_work(conn, session_id="ev-2", item_id="YOK-100")
        mock_emit.assert_called_once()
        args, kwargs = mock_emit.call_args
        assert args[0] == EVENT_WORK_CLAIMED
        assert kwargs["session_id"] == "ev-2"
        assert kwargs["context"]["item_id"] == "100"

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_release_emits_event(self, mock_emit, conn):
        _register(conn, session_id="ev-3")
        mock_emit.reset_mock()
        claim = claim_work(conn, session_id="ev-3", item_id="YOK-101")
        mock_emit.reset_mock()
        release_claim(conn, claim["id"], reason="completed")
        mock_emit.assert_called_once()
        args, kwargs = mock_emit.call_args
        assert args[0] == EVENT_WORK_RELEASED
        assert kwargs["context"]["release_reason"] == "completed"

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_end_session_with_claims_auto_releases_and_emits_release_event(
        self, mock_emit, conn,
    ):
        """No-flags end_session auto-releases and emits HarnessSessionEndReleasedClaims."""
        _register(conn, session_id="ev-4")
        claim_a = claim_work(conn, session_id="ev-4", item_id="YOK-201")
        mock_emit.reset_mock()

        result = end_session(conn, "ev-4")

        assert result["ended_at"] is not None
        assert result["released_claims"][0]["item_id"] == 201
        assert result["released_claims"][0]["claim_id"] == claim_a["id"]

        release_events = [
            c for c in mock_emit.call_args_list
            if c[0][0] == EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS
        ]
        assert len(release_events) == 1
        ctx = release_events[0][1]["context"]
        assert ctx["via"] == "no_flags"
        assert ctx["release_reason"] == "session_ended"

        ended_events = [
            c for c in mock_emit.call_args_list
            if c[0][0] == EVENT_HARNESS_SESSION_ENDED
        ]
        assert len(ended_events) == 1

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_end_session_no_claims_emits_ended_event(self, mock_emit, conn):
        """end_session with no claims emits HarnessSessionEnded."""
        _register(conn, session_id="ev-4b")
        mock_emit.reset_mock()
        end_session(conn, "ev-4b")
        assert mock_emit.call_count == 1
        args, kwargs = mock_emit.call_args
        assert args[0] == EVENT_HARNESS_SESSION_ENDED
        assert kwargs["session_id"] == "ev-4b"

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_reclaim_emits_event(self, mock_emit, conn):
        _register(conn, session_id="ev-5")
        claim = claim_work(conn, session_id="ev-5", item_id="YOK-500")
        # Manually set stale heartbeat
        conn.execute(
            "UPDATE harness_sessions SET last_heartbeat = %s WHERE session_id = 'ev-5'",
            (_STALE_TS,),
        )
        conn.commit()
        mock_emit.reset_mock()
        reclaim_stale_session(conn, "ev-5")
        # One WorkReclaimed event per active claim (AC-2: item_id populated)
        mock_emit.assert_called_once()
        args, kwargs = mock_emit.call_args
        assert args[0] == EVENT_WORK_RECLAIMED
        assert kwargs["session_id"] == "ev-5"
        assert kwargs["item_id"] == "500"
        assert kwargs["context"]["claim_id"] == claim["id"]

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_reclaim_stale_item_claims_emits_offer_reclaim_event(self, mock_emit, conn):
        _register(conn, session_id="ev-5b")
        claim = claim_work(conn, session_id="ev-5b", item_id="YOK-501")
        conn.execute(
            "UPDATE harness_sessions SET last_heartbeat = %s WHERE session_id = 'ev-5b'",
            (_STALE_TS,),
        )
        conn.execute(
            "UPDATE work_claims SET claimed_at = %s, last_heartbeat = %s WHERE id = %s",
            (_STALE_TS, _STALE_TS, claim["id"]),
        )
        conn.commit()
        mock_emit.reset_mock()

        released = reclaim_stale_item_claims(conn, "YOK-501")

        assert released == 1
        mock_emit.assert_called_once()
        args, kwargs = mock_emit.call_args
        assert args[0] == EVENT_WORK_RECLAIMED
        assert kwargs["session_id"] == "ev-5b"
        assert kwargs["item_id"] == "501"
        assert kwargs["context"]["claim_id"] == claim["id"]
        assert kwargs["context"]["reason"] == "stale_item_claim_reclaimed"
        assert kwargs["context"]["reclaimed_by_item_offer"] is True

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_handoff_emits_event(self, mock_emit, conn):
        _register(conn, session_id="ev-6")
        _register(conn, session_id="ev-7")
        mock_emit.reset_mock()
        claim = claim_work(conn, session_id="ev-6", item_id="YOK-200")
        mock_emit.reset_mock()
        handoff_claim(conn, claim["id"], "ev-7")
        mock_emit.assert_called_once()
        args, kwargs = mock_emit.call_args
        assert args[0] == EVENT_WORK_HANDED_OFF
        assert kwargs["context"]["source_session_id"] == "ev-6"
        assert kwargs["context"]["target_session_id"] == "ev-7"
        # Top-level item_id populated
        assert kwargs["item_id"] == "200"


class TestEmitSessionEventHelper:
    @patch("yoke_core.domain.events.emit_event")
    def test_uses_valid_backend_source_type(self, mock_emit):
        _emit_session_event(EVENT_HARNESS_SESSION_STARTED, session_id="sess-emit")
        mock_emit.assert_called_once()
        kwargs = mock_emit.call_args.kwargs
        assert kwargs["source_type"] == "backend"

    @patch("yoke_core.domain.events.emit_event")
    def test_passes_item_id_and_task_num(self, mock_emit):
        """AC-2: item_id and task_num are forwarded to the native emitter."""
        _emit_session_event(
            EVENT_WORK_CLAIMED,
            session_id="sess-idx",
            item_id="YOK-9999",
            task_num=3,
        )
        kwargs = mock_emit.call_args.kwargs
        assert kwargs["item_id"] == "YOK-9999"
        assert kwargs["task_num"] == 3

    @patch("yoke_core.domain.events.emit_event")
    def test_omits_item_id_when_none(self, mock_emit):
        """When item_id is None, it is passed as None to the native emitter."""
        _emit_session_event(
            EVENT_HARNESS_SESSION_STARTED,
            session_id="sess-no-item",
        )
        kwargs = mock_emit.call_args.kwargs
        assert kwargs.get("item_id") is None
        assert kwargs.get("task_num") is None


class TestSessionRouteImports:
    def test_sessions_route_imports_without_main_preload(self):
        result = subprocess.run(
            [sys.executable, "-c", "import yoke_core.api.routes.sessions"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr


class TestNextActionChosenEmission:
    @patch("yoke_core.domain.events.emit_event")
    def test_charge_uses_workflow_contract_and_indexes_item(self, mock_emit):
        emit_next_action_chosen(
            session_id="sess-charge",
            action="charge",
            reason="Ready item selected",
            correlation_id="sess-charge",
            chainable=True,
            step=2,
            context={
                "selected_item": "YOK-9999",
                "scheduler": {"next_step": "conduct"},
            },
        )

        # The _emit_event wrapper calls the native emitter
        mock_emit.assert_called_once()
        call_args = mock_emit.call_args
        assert call_args.args[0] == "NextActionChosen"
        kwargs = call_args.kwargs
        assert kwargs["event_kind"] == "workflow"
        assert kwargs["event_type"] == "session_directive"
        assert kwargs["source_type"] == "backend"
        assert kwargs["severity"] == "STATUS"
        assert kwargs["item_id"] == "YOK-9999"
        ctx = kwargs["context"]
        assert ctx["chainable"] is True
        assert ctx["step"] == 2
        assert ctx["selected_item"] == "YOK-9999"

    @patch("yoke_core.domain.events.emit_event")
    def test_resume_indexes_item_and_task_num(self, mock_emit):
        emit_next_action_chosen(
            session_id="sess-resume",
            action="resume",
            reason="Resume active claim",
            correlation_id="sess-resume",
            project="buzz",
            chainable=True,
            step=3,
            context={
                "item_id": "YOK-9",
                "task_num": 4,
                "status": "active",
            },
        )

        kwargs = mock_emit.call_args.kwargs
        assert kwargs["item_id"] == "YOK-9"
        assert kwargs["task_num"] == 4
        assert kwargs["project"] == "buzz"
        ctx = kwargs["context"]
        assert ctx["item_id"] == "YOK-9"
        assert ctx["task_num"] == 4
        assert ctx["step"] == 3
