"""session-begin level resolution tests for yoke_core.api.service_client.

Sibling files:
- test_service_client_sessions_touch.py (session-touch)
- test_service_client_sessions_checkpoint.py (session-checkpoint)
- test_service_client_sessions_resolve.py (session-id auto-resolution)
- test_service_client_sessions_helpers.py (shared fixture + helpers)
"""

from __future__ import annotations

import json
import uuid

import pytest

from yoke_contracts.session_level import UNRESOLVED_EXECUTION_LEVEL
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.fixtures.level_store import (
    levels_doc,
    option,
    store_project_levels,
    store_universe_levels,
)
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    session_test_db as session_test_db,
)
from runtime.api.test_constants import TEST_MODEL_ID

_PROJECT_ID = 1
_OPUS = "claude-opus-5-5"
_UNIVERSE_DOC = levels_doc(("UNIVERSE_ONLY", [option("claude-cli", _OPUS, "medium")]))
_PROJECT_DOC = levels_doc(("PROJECT_ONLY", [option("claude-cli", _OPUS, "medium")]))


def _begin(db: dict, executor: str, *extra: str) -> str:
    """Run ``session-begin`` for a fresh session and return its id."""
    session_id = f"reg-{uuid.uuid4().hex[:8]}"
    result = _run_client(
        [
            "session-begin",
            "--session-id",
            session_id,
            "--executor",
            executor,
            "--provider",
            "test-provider",
            "--workspace",
            db["tmp_dir"],
            "--project-id",
            str(_PROJECT_ID),
            *extra,
        ],
        db_path=db["db_path"],
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    return session_id


def _session_row(db: dict, session_id: str):
    conn = connect_test_db(db["db_path"])
    try:
        row = conn.execute(
            "SELECT executor, executor_surface, execution_level "
            "FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        event = conn.execute(
            "SELECT envelope FROM events WHERE event_name = "
            "'HarnessSessionStarted' AND session_id = %s ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    context = json.loads(event[0])["context"] if event is not None else None
    return tuple(row), context


def _store(db: dict, writer, *args) -> None:
    conn = connect_test_db(db["db_path"])
    try:
        writer(conn, *args)
    finally:
        conn.close()


class TestSessionBeginLevel:
    """session-begin stamps the level its harness, model, and effort match."""

    @pytest.mark.parametrize(
        "executor,flags,expected",
        [
            ("codex", ("--model", "gpt-6-luna", "--reasoning-effort", "max"), "INTERN"),
            ("claude-code", ("--requested-model", f"{_OPUS}[1m]"), "SENIOR"),
            (
                "claude-code",
                ("--model", "claude-haiku-5-5", "--reasoning-effort", "max"),
                "INTERN",
            ),
            ("claude-code", ("--model", "claude-unlisted"), UNRESOLVED_EXECUTION_LEVEL),
        ],
    )
    def test_shipped_options_label_when_nothing_is_stored(
        self, session_test_db, executor, flags, expected
    ):
        session_id = _begin(session_test_db, executor, *flags)
        (_executor, _surface, level), _context = _session_row(
            session_test_db, session_id
        )
        assert level == expected

    def test_stored_universe_definition_changes_the_stamp(self, session_test_db):
        _store(session_test_db, store_universe_levels, _UNIVERSE_DOC)
        session_id = _begin(session_test_db, "claude-code", "--model", _OPUS)
        (_executor, _surface, level), _context = _session_row(
            session_test_db, session_id
        )
        assert level == "UNIVERSE_ONLY"

    def test_project_override_wins_over_the_universe(self, session_test_db):
        _store(session_test_db, store_universe_levels, _UNIVERSE_DOC)
        _store(session_test_db, store_project_levels, _PROJECT_ID, _PROJECT_DOC)
        session_id = _begin(session_test_db, "claude-code", "--model", _OPUS)
        (_executor, _surface, level), _context = _session_row(
            session_test_db, session_id
        )
        assert level == "PROJECT_ONLY"

    def test_session_begin_accepts_entrypoint_and_emits_it(self, session_test_db):
        session_id = _begin(
            session_test_db,
            "codex",
            "--model",
            "gpt-6.1-sol",
            "--entrypoint",
            "codex-desktop",
        )
        (executor, surface, level), context = _session_row(session_test_db, session_id)

        # Canonical executor stored; surface alias preserved as display.
        assert (executor, surface) == ("codex", "codex-desktop")
        assert level == "SENIOR"
        assert context["executor"] == "codex"
        assert context["executor_surface"] == "codex-desktop"
        assert context["entrypoint"] == "codex-desktop"

    @pytest.mark.parametrize(
        "executor,entrypoint",
        [("claude-code", "claude-vscode"), ("claude", "claude-desktop")],
    )
    def test_entrypoint_surface_keeps_the_family_option_match(
        self, session_test_db, executor, entrypoint
    ):
        session_id = _begin(
            session_test_db,
            executor,
            "--requested-model",
            f"{_OPUS}[1m]",
            "--entrypoint",
            entrypoint,
        )
        (stored_executor, surface, level), context = _session_row(
            session_test_db, session_id
        )

        # A legacy alias canonicalizes; the entrypoint lands as the surface,
        # and the surface's harness family matches the shipped option.
        assert (stored_executor, surface) == ("claude-code", entrypoint)
        assert level == "SENIOR"
        assert context["executor"] == "claude-code"
        assert context["executor_surface"] == entrypoint
        assert context["entrypoint"] == entrypoint

    def test_opaque_model_without_an_option_stays_unresolved(self, session_test_db):
        session_id = _begin(session_test_db, "claude-code", "--model", TEST_MODEL_ID)
        (_executor, _surface, level), _context = _session_row(
            session_test_db, session_id
        )
        assert level == UNRESOLVED_EXECUTION_LEVEL
