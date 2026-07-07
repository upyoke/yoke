"""Session lifecycle tests: human-only operator override release.

Split from test_sessions_lifecycle_chain.py: TestOperatorOverrideReleaseClaim.
"""

from __future__ import annotations

import os

import pytest
from unittest.mock import patch

from runtime.api.test_sessions import (
    _register,
    conn,  # noqa: F401  (Postgres-backed pytest fixture)
)
from yoke_core.domain.sessions import (
    EVENT_OPERATOR_CLAIM_OVERRIDE,
    EVENT_WORK_RELEASED,
    SessionError,
    claim_work,
    operator_override_release_claim,
)


class TestOperatorOverrideReleaseClaim:
    """FR-4: Human-only operator override."""

    def test_ac7_release_targeted_claim(self, conn):
        """AC-7: Override releases only the targeted claim atomically."""
        _register(conn)
        c1 = claim_work(conn, session_id="sess-1", item_id="YOK-10")
        c2 = claim_work(conn, session_id="sess-1", item_id="YOK-20")
        result = operator_override_release_claim(
            conn, "YOK-10", "stranded after crash",
        )
        assert result["released"] is True
        assert result["claim_id"] == c1["id"]
        assert result["item_id"] == "10"
        # Second claim still active
        active = conn.execute(
            "SELECT COUNT(*) as cnt FROM work_claims WHERE session_id='sess-1' AND released_at IS NULL"
        ).fetchone()
        assert active["cnt"] == 1
        # Released claim has canonical reason
        released_row = conn.execute(
            "SELECT release_reason FROM work_claims WHERE id=%s", (c1["id"],)
        ).fetchone()
        assert released_row["release_reason"] == "released"

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_ac7_emits_both_events(self, mock_emit, conn):
        """AC-7: Override emits WorkReleased + OperatorClaimOverride."""
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-10")
        mock_emit.reset_mock()
        operator_override_release_claim(conn, "YOK-10", "test override")
        event_names = [c[0][0] for c in mock_emit.call_args_list]
        assert EVENT_WORK_RELEASED in event_names
        assert EVENT_OPERATOR_CLAIM_OVERRIDE in event_names
        # Check WorkReleased has operator-override intent
        wr_call = [c for c in mock_emit.call_args_list if c[0][0] == EVENT_WORK_RELEASED][0]
        assert wr_call[1]["context"]["release_reason_intent"] == "operator-override"

    def test_ac7_rejects_hook_context(self, conn):
        """AC-7: Override rejects when YOKE_HOOK_EVENT is set."""
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-10")
        with patch.dict(os.environ, {"YOKE_HOOK_EVENT": "SessionEnd"}):
            with pytest.raises(SessionError) as exc_info:
                operator_override_release_claim(conn, "YOK-10", "sneaky hook")
            assert exc_info.value.code == "HOOK_CONTEXT"

    def test_not_found_raises(self, conn):
        _register(conn)
        with pytest.raises(SessionError) as exc_info:
            operator_override_release_claim(conn, "YOK-999", "no such claim")
        assert exc_info.value.code == "NOT_FOUND"

    def test_by_claim_id(self, conn):
        _register(conn)
        c = claim_work(conn, session_id="sess-1", item_id="YOK-10")
        result = operator_override_release_claim(
            conn, "YOK-10", "by claim id", claim_id=c["id"],
        )
        assert result["released"] is True
        assert result["claim_id"] == c["id"]
