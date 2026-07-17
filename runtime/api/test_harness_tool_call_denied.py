"""End-to-end coverage for HarnessToolCallDenied emission.

Every Yoke-owned PreToolUse deny path emits exactly one
``HarnessToolCallDenied`` row carrying ``session_id``, ``tool_name``, a
command/args snippet, the lint identifier, and the deny reason. AC-2: when
multiple lints would deny the same call, only the first denier emits (no
duplicate rows per attempt). AC-7: the DB-command guard
(``lint_db_cmd``)
shares the same ``emit_denial_event`` contract as the other Python deniers.

These tests drive representative lints end-to-end — denier invoked → deny
JSON returned → a real row lands in an isolated events DB — without
mocking the emit path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from yoke_core.domain import events_crud
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def events_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated events DB pointed to by ``YOKE_DB``.

    On Postgres the schema lands in a disposable per-test database (YOKE_PG_DSN
    repointed for the context), so the deniers' ``emit_event`` writes and the
    readback below hit the same isolated DB — never the shared ambient one that
    would collide under ``-n``. On SQLite it is a file under ``tmp_path``.
    """
    with init_test_db(tmp_path, apply_schema=events_crud.cmd_init) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _fetch_denials(db_path: str) -> list[dict]:
    """Return every ``HarnessToolCallDenied`` row as a dict."""
    conn = connect_test_db(db_path)
    try:
        rows = conn.execute(
            "SELECT event_name, session_id, tool_name, severity, envelope "
            "FROM events WHERE event_name = 'HarnessToolCallDenied' "
            "ORDER BY created_at ASC"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# AC-6 core: each denier emits exactly one HarnessToolCallDenied row
# ---------------------------------------------------------------------------


class TestHarnessToolCallDeniedEndToEnd:
    def test_lint_main_commit_emits_single_row_with_expected_envelope(
        self, events_db: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-1 / AC-6: a lint-main-commit deny produces one row with all
        required fields (session_id, tool_name, command snippet, lint
        identifier, reason)."""
        from yoke_core.domain import lint_main_commit as lmc

        # Force the deny branch: pretend current branch is main, staged files
        # contain non-bookkeeping paths, and at least one active worktree item
        # exists. ``_active_worktree_items`` returns ``"id|title"`` strings.
        monkeypatch.setattr(lmc, "_current_branch", lambda: "main")
        monkeypatch.setattr(
            lmc,
            "_staged_files",
            lambda: ["runtime/api/domain/foo.py"],
        )
        monkeypatch.setattr(
            lmc,
            "_active_worktree_items",
            lambda: ["42|Fix the thing"],
        )

        payload = {
            "session_id": "sess-lmc-1",
            "tool_use_id": "tu-lmc-1",
            "tool_name": "Bash",
            "tool_input": {
                "command": "git commit -m 'implementation on main'",
            },
        }
        decision = lmc.evaluate(lmc._build_context_from_payload(payload))
        # Trigger the deny side-effect (denial event emission) the legacy
        # ``run(...)`` form used to do; the typed evaluator emits the event
        # inside ``evaluate`` in the deny branch — assert PASS via outcome.
        assert decision is not None

        rows = _fetch_denials(events_db)
        assert len(rows) == 1, f"expected exactly one denial row, got {rows}"

        row = rows[0]
        assert row["tool_name"] == "Bash"
        assert row["session_id"] == "sess-lmc-1"
        assert row["severity"] == "WARN"

        envelope = json.loads(row["envelope"])
        assert envelope["event_name"] == "HarnessToolCallDenied"
        assert envelope["tool_use_id"] == "tu-lmc-1"

        detail = envelope["context"]["detail"]
        assert detail["hook"] == "lint-main-commit"
        assert detail["check_id"] == "impl_on_main"
        assert "command_snippet" in detail, (
            "command_snippet must be present so operators can see which "
            "call was blocked"
        )
        assert "git commit" in detail["command_snippet"]
        assert isinstance(detail["reason"], str)
        assert detail["reason"]

    def test_lint_db_cmd_main_emits_legacy_denied_row_for_blocked_command(
        self, events_db: str
    ) -> None:
        """AC-7: DB-command deniers share the same emit contract as the
        other Python deniers. Driving ``lint_db_cmd.main`` with a payload
        the policy denies must preserve the legacy stable
        ``lint-sqlite-cmd`` hook/check id and the command snippet."""
        from yoke_core.domain import lint_db_cmd as ldc

        payload = {
            "session_id": "sess-sqlite-1",
            "tool_use_id": "tu-sqlite-1",
            "tool_name": "Bash",
            "tool_input": {
                "command": 'sqlite3 data/yoke.db "SELECT * FROM items"',
            },
        }

        raw = json.dumps(payload)

        class _FakeStdin:
            def __init__(self, data: str) -> None:
                self._data = data

            def read(self) -> str:
                return self._data

        import sys as _sys

        real_stdin = _sys.stdin
        _sys.stdin = _FakeStdin(raw)  # type: ignore[assignment]
        try:
            rc = ldc.main()
        finally:
            _sys.stdin = real_stdin

        assert rc == 0

        rows = _fetch_denials(events_db)
        assert len(rows) == 1, f"expected one denial row, got {rows}"

        envelope = json.loads(rows[0]["envelope"])
        detail = envelope["context"]["detail"]
        assert detail["hook"] == "lint-sqlite-cmd"
        assert detail["check_id"] == "lint-sqlite-cmd"
        assert "sqlite3" in detail["command_snippet"]
        assert envelope["event_name"] == "HarnessToolCallDenied"
        assert rows[0]["session_id"] == "sess-sqlite-1"

    def test_lint_main_commit_emits_nothing_when_allowed(
        self, events_db: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-3 / happy path: no emit when the lint allows the call."""
        from yoke_core.domain import lint_main_commit as lmc

        # Simulate an allow: non-main branch short-circuits.
        monkeypatch.setattr(lmc, "_current_branch", lambda: "feature-branch")
        payload = {
            "session_id": "sess-none",
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'ok'"},
        }
        lmc.evaluate(lmc._build_context_from_payload(payload))
        assert _fetch_denials(events_db) == []


# ---------------------------------------------------------------------------
# First-denier-wins semantics. Two different lints deny the same
# payload; each emits exactly one row. Running them *sequentially* against
# the same payload — as the Claude PreToolUse chain would do — must not
# produce two rows for the *same* attempt. Python harness behavior already
# enforces "first denier short-circuits the chain"; Yoke's deniers only
# run when reached. This test documents the invariant by asserting that a
# sequence of deniers driven in isolation each emits its own single row
# (one emission per reached denier). If two reach the same payload, the
# PreToolUse harness is expected to short-circuit after the first, so only
# one row lands — consumers can trust "one HarnessToolCallDenied per
# blocked attempt" in telemetry.
# ---------------------------------------------------------------------------


class TestSingleEmitPerDenier:
    def test_each_reached_denier_emits_exactly_once(
        self, events_db: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from yoke_core.domain import lint_main_commit as lmc

        monkeypatch.setattr(lmc, "_current_branch", lambda: "main")
        monkeypatch.setattr(
            lmc,
            "_staged_files",
            lambda: ["runtime/api/domain/foo.py"],
        )
        monkeypatch.setattr(
            lmc,
            "_active_worktree_items",
            lambda: ["42|Fix the thing"],
        )

        payload = {
            "session_id": "sess-single",
            "tool_use_id": "tu-single",
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'deny me'"},
        }
        # Invoke the single reached denier exactly once.
        lmc.evaluate(lmc._build_context_from_payload(payload))
        rows = _fetch_denials(events_db)
        assert len(rows) == 1, (
            "one reached denier must produce exactly one row per attempt "
            "(AC-2: no duplicate HarnessToolCallDenied rows)"
        )
