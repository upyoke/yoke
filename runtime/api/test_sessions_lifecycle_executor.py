"""Executor canonicalization + surface-alias coverage for ``register_session``.

Companion to ``test_sessions_lifecycle.py``; split out to keep both
files under the 350-line authored cap.
"""

from __future__ import annotations

import pytest

from runtime.api.test_sessions import (
    _register,
    conn as conn,
)


class TestRegisterCanonicalizesExecutor:
    """Surface-specific inputs become ``(canonical, surface)`` splits.

    The contract: ``harness_sessions.executor`` stores only a closed canonical
    harness id after register; the surface-specific input (when known) is
    preserved in ``executor_surface``. Custom values are refused.
    """

    def test_register_canonical_executor_stored_with_display_alias(self, conn):
        for surface, canonical in (
            ("claude-desktop", "claude-code"),
            ("claude-vscode", "claude-code"),
            ("codex-desktop", "codex"),
            ("codex-cli", "codex"),
        ):
            session_id = f"canonical-{surface}"
            result = _register(conn, session_id=session_id, executor=surface)
            assert result["executor"] == canonical
            assert result["executor_surface"] == surface

    def test_register_coarse_executor_stores_no_display_alias(self, conn):
        """Coarse executor inputs (no surface specificity) store NULL display."""
        result = _register(conn, session_id="legacy-claude", executor="claude")
        assert result["executor"] == "claude-code"
        assert result["executor_surface"] is None

        result = _register(conn, session_id="coarse-claude", executor="claude-code")
        assert result["executor"] == "claude-code"
        assert result["executor_surface"] is None

        result = _register(conn, session_id="coarse-codex", executor="codex")
        assert result["executor"] == "codex"
        assert result["executor_surface"] is None

    def test_register_unknown_executor_is_refused(self, conn):
        """An override cannot invent a persisted executor family."""
        with pytest.raises(ValueError, match="unknown harness executor family"):
            _register(conn, session_id="custom", executor="DARIUS")

    def test_register_persists_valid_observed_machine_facts(self, conn):
        machine_id = "00000000-0000-4000-8000-000000000123"
        result = _register(
            conn,
            session_id="observed",
            executor="codex-cli",
            executor_version="0.148.0-alpha.15",
            machine_id=machine_id,
        )
        assert result["executor_version"] == "0.148.0-alpha.15"
        assert result["machine_id"] == machine_id

    def test_register_refuses_noncanonical_machine_id(self, conn):
        from yoke_core.domain.sessions import SessionError

        with pytest.raises(SessionError) as caught:
            _register(
                conn,
                session_id="invalid-machine",
                machine_id="machine-one",
            )
        assert caught.value.code == "MACHINE_ID_INVALID"
