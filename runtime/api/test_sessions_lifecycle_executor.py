"""Executor canonicalization + display-alias coverage for ``register_session``.

Companion to ``test_sessions_lifecycle.py``; split out to keep both
files under the 350-line authored cap.
"""

from __future__ import annotations

from runtime.api.test_sessions import (
    _register,
    conn,  # noqa: F401  (pytest fixture)
)


class TestRegisterCanonicalizesExecutor:
    """Surface-specific inputs become ``(canonical, display_name)`` splits.

    The contract: ``harness_sessions.executor`` stores only ``claude-code``
    or ``codex`` after register; the surface-specific input (when known) is
    preserved in ``executor_display_name``. Custom values pass through.
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
            assert result["executor_display_name"] == surface

    def test_register_coarse_executor_stores_no_display_alias(self, conn):
        """Coarse executor inputs (no surface specificity) store NULL display."""
        result = _register(conn, session_id="legacy-claude", executor="claude")
        assert result["executor"] == "claude-code"
        assert result["executor_display_name"] is None

        result = _register(conn, session_id="coarse-claude", executor="claude-code")
        assert result["executor"] == "claude-code"
        assert result["executor_display_name"] is None

        result = _register(conn, session_id="coarse-codex", executor="codex")
        assert result["executor"] == "codex"
        assert result["executor_display_name"] is None

    def test_register_custom_executor_passes_through(self, conn):
        """YOKE_EXECUTOR override values (unrecognized families) pass through."""
        result = _register(conn, session_id="custom", executor="DARIUS")
        assert result["executor"] == "DARIUS"
        assert result["executor_display_name"] is None
