"""TestReleaseClaimsForDoneItem: AC-1, AC-2, AC-5 foreign-claim cleanup."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.test_sessions import _register, conn  # noqa: F401  (pytest fixture)
from yoke_core.domain import db_backend
from yoke_core.domain.sessions import (
    EVENT_WORK_RELEASED,
    claim_work,
    release_claim,
    release_claims_for_done_item,
)
from runtime.api.sessions_api_stale_test_helpers import _now_literal


class TestReleaseClaimsForDoneItem:
    """Tests for item-done foreign-claim cleanup."""

    def test_releases_unreleased_claims_on_done_item(self, conn):
        """AC-1: When an item transitions to done, any unreleased exclusive
        claim is released, even if it belongs to a different session."""
        _register(conn, session_id="stale-sess")
        claim = claim_work(conn, session_id="stale-sess", item_id="YOK-9999")

        released = release_claims_for_done_item(conn, "YOK-9999")

        assert released == 1
        row = conn.execute(
            "SELECT released_at, release_reason FROM work_claims WHERE id = %s",
            (claim["id"],),
        ).fetchone()
        assert row["released_at"] is not None
        assert row["release_reason"] == "completed"

    def test_no_claims_returns_zero(self, conn):
        """No unreleased claims -> returns 0, does not error."""
        released = release_claims_for_done_item(conn, "YOK-999")
        assert released == 0

    def test_skips_already_released_claims(self, conn):
        """Already-released claims are not double-released."""
        _register(conn, session_id="old-sess")
        claim = claim_work(conn, session_id="old-sess", item_id="YOK-9999")
        release_claim(conn, claim["id"], reason="session_ended")

        released = release_claims_for_done_item(conn, "YOK-9999")
        assert released == 0

    def test_active_item_unique_index_prevents_residue_scenario(self, conn):
        """The partial unique index ``idx_work_claims_active_item`` now
        prevents the historical residue scenario this test originally
        exercised. Two unreleased claims on the same ``item_id`` can no
        longer coexist: the second insert raises ``IntegrityError`` and
        the storage layer is the authoritative prevention point. The
        single-claim cleanup path is covered by the AC-1 test above and
        by ``test_regression_claim_row_residue`` below."""
        _register(conn, session_id="sess-a")
        _register(conn, session_id="sess-b")
        claim_work(conn, session_id="sess-a", item_id="YOK-9999")
        _ts = _now_literal()
        with pytest.raises(db_backend.integrity_error_types()):
            conn.execute(
                """INSERT INTO work_claims
                   (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
                   VALUES ('sess-b', 'item', 9999, 'exclusive', %s, %s)""",
                (_ts, _ts),
            )

    @patch("yoke_core.domain.sessions_analytics._emit_event")
    def test_emits_per_claim_telemetry(self, mock_emit, conn):
        """AC-2: Per-claim release telemetry with populated item context."""
        _register(conn, session_id="stale-sess")
        claim_work(conn, session_id="stale-sess", item_id="YOK-9999")

        release_claims_for_done_item(conn, "YOK-9999")

        released_calls = [c for c in mock_emit.call_args_list
                          if c[0][0] == EVENT_WORK_RELEASED]
        assert len(released_calls) == 1
        kw = released_calls[0][1]
        assert kw["session_id"] == "stale-sess"
        assert kw["item_id"] == "9999"
        assert kw["context"]["release_reason"] == "completed"
        assert kw["context"]["cleanup_reason"] == "item_done"

    def test_regression_claim_row_residue(self, conn):
        """AC-4: The regression example -- residue like a lingering claim row
        can be cleaned up without manual DB edits."""
        _register(conn, session_id="claude-code-20260406T022557Z-94581")
        claim = claim_work(
            conn,
            session_id="claude-code-20260406T022557Z-94581",
            item_id="YOK-1187",
        )
        # Item completed in a different session -- claim is still unreleased
        released = release_claims_for_done_item(conn, "YOK-1187")
        assert released == 1
        row = conn.execute(
            "SELECT release_reason FROM work_claims WHERE id = %s",
            (claim["id"],),
        ).fetchone()
        assert row["release_reason"] == "completed"
