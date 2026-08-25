"""``register_session`` native_thread_id coverage.

Split out alongside ``test_sessions_lifecycle_actor_id.py`` rather than
grown into the already-near-budget parent file. ``native_thread_id`` is
the harness's own thread identity (Codex's ``CODEX_THREAD_ID``) — distinct
from ``session_id``, since an operator-started Codex session registers
under its own session id while the app-server keys its thread on a
different value. Wake resolves against this stored column instead of
assuming the two agree (that assumption only holds for a plane-launched
session, which the launch flow separately asserts).

The shared `conn` fixture and `_register` helper come from the sibling
test_sessions module so the schema and registration default kwargs match
the parent suite.
"""

from __future__ import annotations

import pytest

from runtime.api.test_sessions import _p, _register
from yoke_core.domain.sessions import SessionError, end_session

pytest_plugins = ("runtime.api.test_sessions",)


class TestRegisterSessionNativeThreadId:
    def test_register_persists_native_thread_id(self, conn):
        result = _register(
            conn, session_id="sess-thread", native_thread_id="thread-42"
        )
        assert result["native_thread_id"] == "thread-42"

    def test_register_defaults_to_null_when_absent(self, conn):
        result = _register(conn, session_id="sess-nothread")
        assert result["native_thread_id"] is None

    def test_reactivation_backfills_when_previously_unknown(self, conn):
        """An ended session with no captured thread id learns it on
        reactivation instead of staying permanently unmapped.
        """
        _register(conn, session_id="sess-backfill")
        end_session(conn, "sess-backfill")

        result = _register(
            conn, session_id="sess-backfill", native_thread_id="thread-99"
        )

        assert result["native_thread_id"] == "thread-99"

    def test_reactivation_keeps_stored_value_when_caller_has_none(self, conn):
        """A later reactivation with no CODEX_THREAD_ID in scope (e.g. a
        different harness re-touching the row) must not erase a
        previously captured mapping.
        """
        _register(conn, session_id="sess-keep", native_thread_id="thread-1")
        end_session(conn, "sess-keep")

        result = _register(conn, session_id="sess-keep")

        assert result["native_thread_id"] == "thread-1"

    def test_active_duplicate_upgrades_in_place_when_previously_unknown(self, conn):
        """The common repeat-registration path on an already-active
        session (UserPromptSubmit's safety net) still learns the mapping
        even though the insert conflicts with SESSION_EXISTS.
        """
        _register(conn, session_id="sess-upgrade")
        with pytest.raises(SessionError) as exc_info:
            _register(
                conn, session_id="sess-upgrade", native_thread_id="thread-7"
            )
        assert exc_info.value.code == "SESSION_EXISTS"

        row = conn.execute(
            f"SELECT native_thread_id FROM harness_sessions "
            f"WHERE session_id = {_p(conn)}",
            ("sess-upgrade",),
        ).fetchone()
        assert row["native_thread_id"] == "thread-7"

    def test_register_tolerates_schema_without_native_thread_id(self, conn):
        """Hand-built fixtures often omit independently evolving columns."""
        conn.execute("ALTER TABLE harness_sessions DROP COLUMN native_thread_id")
        conn.commit()
        result = _register(
            conn, session_id="sess-no-col", native_thread_id="thread-ignored"
        )
        assert "native_thread_id" not in result

    def test_active_duplicate_never_overwrites_stored_mapping(self, conn):
        """Once a thread id is known, a later re-registration (even one
        that observed a different or blank value) never clobbers it.
        """
        _register(conn, session_id="sess-stable", native_thread_id="thread-1")
        with pytest.raises(SessionError):
            _register(conn, session_id="sess-stable", native_thread_id="thread-2")

        row = conn.execute(
            f"SELECT native_thread_id FROM harness_sessions "
            f"WHERE session_id = {_p(conn)}",
            ("sess-stable",),
        ).fetchone()
        assert row["native_thread_id"] == "thread-1"
