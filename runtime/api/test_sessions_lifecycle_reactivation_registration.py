"""Session registration reactivation advisory wiring tests."""

from unittest import mock

from runtime.api.test_sessions_lifecycle_reactivation_claims import (
    _insert_claim,
    _insert_session,
    _ReactivationDBTest,
)
from yoke_core.domain.sessions_lifecycle_reactivation import (
    emit_reactivated_with_released_claims,
)


class TestRegisterSessionReactivationWiring(_ReactivationDBTest):
    """Integration: register_session emits advisory on reactivation."""

    def test_reactivation_calls_advisory_helper(self) -> None:
        """register_session calls emit_reactivated_with_released_claims on reactivation.

        The helper returns the released claims list — non-empty confirms the
        reactivation path fired.  (The native event emitter writes to the global
        canonical DB, so we verify via the helper's return contract rather than
        checking the in-memory test DB's events table.)
        """
        from yoke_core.domain.sessions_lifecycle_registry import register_session

        conn = self.conn
        _insert_session(conn, "sess-reac", ended=True)
        _insert_claim(
            conn, "sess-reac", 999, released=True, release_reason="session_ended"
        )

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_registry.emit_reactivated_with_released_claims",
            return_value=[{"target_kind": "item", "item_id": 999}],
        ) as advisory:
            # register_session must not raise on reactivation
            register_session(
                conn,
                session_id="sess-reac",
                executor="claude-code",
                provider="anthropic",
                model="claude-sonnet-4-6",
                workspace="/tmp",
                project_id=1,
            )
        advisory.assert_called_once()
        self.assertIs(advisory.call_args.args[0], conn)
        self.assertEqual(advisory.call_args.args[1], "sess-reac")
        # If we reach here without exception, the reactivation path ran cleanly

    def test_fresh_session_no_released_claims(self) -> None:
        """Fresh session has no prior session-ended claims — helper returns empty list."""
        conn = self.conn
        _insert_session(conn, "sess-fresh")

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
        ) as emit_event:
            result = emit_reactivated_with_released_claims(conn, "sess-fresh")
        self.assertEqual(
            result, [], "Fresh session must not return any released claims"
        )
        emit_event.assert_not_called()

    def test_fresh_registration_does_not_call_advisory_helper(self) -> None:
        """Only same-session reactivation calls the released-claims advisory helper."""
        from yoke_core.domain.sessions_lifecycle_registry import register_session

        conn = self.conn

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_registry.emit_reactivated_with_released_claims"
        ) as advisory:
            register_session(
                conn,
                session_id="sess-new",
                executor="claude-code",
                provider="anthropic",
                model="claude-sonnet-4-6",
                workspace="/tmp",
                project_id=1,
            )
        advisory.assert_not_called()
