"""End-to-end registration behavior of ``begin_session``.

Exercises the shared registration core against a real backend: idempotent
re-registration, and the executor/entrypoint split that decides what lands
in ``harness_sessions.executor`` versus ``executor_display_name``.

Split from the ``sessions.begin`` function-surface tests, which cover
registration/authz coherence, request parsing, and the adapter's
connection-keyed transport routing.
"""

from __future__ import annotations

from runtime.api.test_constants import TEST_MODEL_ID
from runtime.api.test_service_client_sessions_helpers import (
    session_offer_db,  # noqa: F401 — re-exported fixture
)


class TestBeginSessionIntegration:
    """``begin_session`` registers a real row and is idempotent."""

    def test_registers_and_is_idempotent(self, session_offer_db):
        from yoke_core.api.service_client_sessions_lifecycle_begin import (
            begin_session,
        )
        from yoke_core.domain import db_backend

        conn = db_backend.connect()
        try:
            first = begin_session(
                conn,
                session_id="sid-local",
                executor="claude-code",
                provider="anthropic",
                model=TEST_MODEL_ID,
                workspace=session_offer_db["tmp_dir"],
                project_id=1,
            )
            assert first["success"] is True
            assert "session" in first

            second = begin_session(
                conn,
                session_id="sid-local",
                executor="claude-code",
                provider="anthropic",
                model=TEST_MODEL_ID,
                workspace=session_offer_db["tmp_dir"],
                project_id=1,
            )
            assert second["success"] is True
            assert second.get("already_registered") is True

            row = conn.execute(
                "SELECT session_id FROM harness_sessions WHERE session_id = %s",
                ("sid-local",),
            ).fetchone()
            assert row is not None
        finally:
            conn.close()

    def test_surface_executor_survives_an_entrypoint(self, session_offer_db):
        """The surface a session ran on outranks its entrypoint.

        Composing the two before registration replaces the surface with the
        entrypoint (``codex-desktop`` + ``dash`` -> ``codex-dash``), leaving
        no record of which surface the session actually used.
        """
        from yoke_core.api.service_client_sessions_lifecycle_begin import (
            begin_session,
        )
        from yoke_core.domain import db_backend

        conn = db_backend.connect()
        try:
            begin_session(
                conn,
                session_id="sid-surface",
                executor="codex-desktop",
                provider="openai",
                model=TEST_MODEL_ID,
                workspace=session_offer_db["tmp_dir"],
                project_id=1,
                entrypoint="dash",
            )
            row = conn.execute(
                "SELECT executor, executor_display_name FROM harness_sessions "
                "WHERE session_id = %s",
                ("sid-surface",),
            ).fetchone()
            assert row is not None
            assert row[0] == "codex"
            assert row[1] == "codex-desktop"
        finally:
            conn.close()

    def test_entrypoint_still_names_a_coarse_executor(self, session_offer_db):
        """With no surface to preserve, the entrypoint supplies the alias."""
        from yoke_core.api.service_client_sessions_lifecycle_begin import (
            begin_session,
        )
        from yoke_core.domain import db_backend

        conn = db_backend.connect()
        try:
            begin_session(
                conn,
                session_id="sid-coarse",
                executor="codex",
                provider="openai",
                model=TEST_MODEL_ID,
                workspace=session_offer_db["tmp_dir"],
                project_id=1,
                entrypoint="vscode",
            )
            row = conn.execute(
                "SELECT executor, executor_display_name FROM harness_sessions "
                "WHERE session_id = %s",
                ("sid-coarse",),
            ).fetchone()
            assert row is not None
            assert row[0] == "codex"
            assert row[1] == "codex-vscode"
        finally:
            conn.close()
