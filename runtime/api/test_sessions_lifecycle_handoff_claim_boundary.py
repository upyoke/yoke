# ruff: noqa: F811
"""Explicit session handoff claim-boundary tests."""

from runtime.api.test_sessions import (
    _register,
    conn,  # noqa: F401  (pytest fixture)
)
from runtime.api.test_sessions_lifecycle_claim import (  # noqa: F401
    _seed_claim_items,
)
from yoke_core.domain.sessions import (
    claim_work,
    get_claim_for_work_unit,
    release_claim,
)


# ---------------------------------------------------------------------------
# Handoff claim boundary tests
# ---------------------------------------------------------------------------


class TestHandoffClaimBoundary:
    """Explicit handoffs remain hard command boundaries."""

    def test_handoff_release_leaves_no_active_claim(self, conn):
        """A handoff release no longer grants implicit same-session ownership."""
        _register(conn)
        c = claim_work(conn, session_id="sess-1", item_id="YOK-99")
        release_claim(conn, c["id"], reason="handed_off")

        active = get_claim_for_work_unit(conn, item_id="99")
        assert active is None

    def test_same_session_can_claim_again_explicitly_after_handoff(self, conn):
        """The downstream command can still claim the handed-off item explicitly."""
        _register(conn)
        c = claim_work(conn, session_id="sess-1", item_id="YOK-99")
        release_claim(conn, c["id"], reason="handed_off")

        new_claim = claim_work(conn, session_id="sess-1", item_id="YOK-99")
        assert new_claim["session_id"] == "sess-1"

    def test_different_session_can_claim_after_handoff(self, conn):
        """A new command/session may claim the item after the handoff release."""
        _register(conn, session_id="sess-1")
        _register(conn, session_id="sess-2")
        c = claim_work(conn, session_id="sess-1", item_id="YOK-99")
        release_claim(conn, c["id"], reason="handed_off")

        c2 = claim_work(conn, session_id="sess-2", item_id="YOK-99")
        assert c2["session_id"] == "sess-2"

    def test_completed_release_remains_terminal(self, conn):
        """Completed releases are not resumable without a fresh success path."""
        _register(conn)
        c = claim_work(conn, session_id="sess-1", item_id="YOK-99")
        release_claim(conn, c["id"], reason="completed")

        active = get_claim_for_work_unit(conn, item_id="99")
        assert active is None

    def test_standard_handoff_still_releases_correctly(self, conn):
        """AC-04: standard flow releases the claim, no auto-reacquire by
        a different session picking up polish."""
        from yoke_core.domain.sessions import release_item_claim_for_execution

        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-99")
        result = release_item_claim_for_execution(
            conn, "sess-1", "YOK-99", "handoff-to-polish"
        )
        assert result["released"] is True

        # Claim is now released
        active = get_claim_for_work_unit(conn, item_id="99")
        assert active is None

        # A different session can now claim it
        _register(conn, session_id="sess-2")
        c2 = claim_work(conn, session_id="sess-2", item_id="YOK-99")
        assert c2["session_id"] == "sess-2"
