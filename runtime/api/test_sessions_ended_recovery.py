"""Tests: ended-session registration probe + the recovery command refusals name.

Two halves of one contract. :func:`session_registration_state` is what
lets a hook event revive a session whose row a transient ``SessionEnd``
closed — it must report ``ended`` as a first-class answer, distinct from
both "no row" and "lookup failed". :func:`session_ended_message` is the
fallback for the surfaces that still cannot serve an ended session: the
refusal has to carry a populated re-register command instead of dead-ending.

The end-to-end cases drive real refusals (heartbeat, session mode,
work-claim acquisition) so the message wiring is proven at the surfaces
agents actually hit, not just at the renderer.
"""

from __future__ import annotations

import pytest

from runtime.api.test_sessions import _insert_claimable_item, _register
from yoke_core.domain.sessions import (
    SessionError,
    claim_work,
    end_session,
    heartbeat,
    set_session_mode,
)
from yoke_core.domain.sessions_ended_recovery import (
    RECOVERY_COMMAND,
    session_ended_message,
    session_ended_recovery_command,
    session_registration_state,
)

pytest_plugins = ("runtime.api.test_sessions",)


class TestSessionRegistrationState:
    def test_missing_row_reports_positive_absence(self, conn):
        assert session_registration_state(conn, "nobody") == (False, None, False)

    def test_blank_session_id_reports_absence_without_a_read(self, conn):
        assert session_registration_state(conn, "") == (False, None, False)

    def test_live_row_is_found_and_not_ended(self, conn):
        _register(conn, session_id="live")
        found, _actor_id, ended = session_registration_state(conn, "live")
        assert (found, ended) == (True, False)

    def test_ended_row_is_found_and_ended(self, conn):
        # The sleep/resume shape: the row survives, ended_at is set, and the
        # conversation keeps running. "A row exists" is not enough for the
        # ensure-register probe to skip.
        _register(conn, session_id="slept")
        end_session(conn, "slept")
        found, _actor_id, ended = session_registration_state(conn, "slept")
        assert (found, ended) == (True, True)

    def test_failed_lookup_reports_unknown_rather_than_absent(self):
        class _BrokenConn:
            def execute(self, *_a, **_k):
                raise RuntimeError("connection is gone")

        # A broken connection must not read as "unregistered" — that would
        # spawn a registration attempt per hook event.
        assert session_registration_state(_BrokenConn(), "s") == (None, None, False)


class TestRecoveryCommandRendering:
    def test_renders_populated_re_register_command(self, conn):
        _register(conn, session_id="slept")
        end_session(conn, "slept")
        command = session_ended_recovery_command(conn, "slept")
        assert command.startswith(f"{RECOVERY_COMMAND} --session-id slept ")
        for flag in ("--executor", "--provider", "--model", "--workspace"):
            assert f"{flag} " in command

    def test_quotes_values_that_need_it(self, conn):
        _register(conn, session_id="spacey", workspace="/tmp/a work dir")
        command = session_ended_recovery_command(conn, "spacey")
        assert "--workspace '/tmp/a work dir'" in command

    def test_missing_row_renders_nothing(self, conn):
        assert session_ended_recovery_command(conn, "nobody") == ""

    def test_message_falls_back_to_the_bare_sentence(self, conn):
        message = session_ended_message(conn, "nobody")
        assert message == "Session 'nobody' has already ended."
        assert RECOVERY_COMMAND not in message

    def test_message_appends_the_recovery_command(self, conn):
        _register(conn, session_id="slept")
        end_session(conn, "slept")
        message = session_ended_message(conn, "slept")
        assert message.startswith("Session 'slept' has already ended.")
        assert f"{RECOVERY_COMMAND} --session-id slept" in message


class TestRefusalsNameTheirRecovery:
    """Every agent-facing surface that refuses SESSION_ENDED teaches recovery."""

    def _ended_session(self, conn, session_id="slept"):
        _register(conn, session_id=session_id)
        end_session(conn, session_id)
        return session_id

    def _assert_teaches_recovery(self, exc_info, session_id):
        assert exc_info.value.code == "SESSION_ENDED"
        assert f"{RECOVERY_COMMAND} --session-id {session_id}" in str(
            exc_info.value
        )

    def test_heartbeat_refusal(self, conn):
        session_id = self._ended_session(conn)
        with pytest.raises(SessionError) as exc_info:
            heartbeat(conn, session_id)
        self._assert_teaches_recovery(exc_info, session_id)

    def test_session_mode_refusal(self, conn):
        session_id = self._ended_session(conn)
        with pytest.raises(SessionError) as exc_info:
            set_session_mode(conn, session_id, "dash")
        self._assert_teaches_recovery(exc_info, session_id)

    def test_work_claim_acquisition_refusal(self, conn):
        session_id = self._ended_session(conn)
        _insert_claimable_item(conn, 4242)
        with pytest.raises(SessionError) as exc_info:
            claim_work(conn, session_id=session_id, item_id="4242")
        self._assert_teaches_recovery(exc_info, session_id)
