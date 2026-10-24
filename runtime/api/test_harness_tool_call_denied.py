"""End-to-end coverage for HarnessToolCallDenied recording.

Guards return decisions; the hook runner binds each guard's denial identity
and records the decision through
:func:`yoke_core.hooks.guard_denial_record.record_guard_decision`, so every
Yoke-owned PreToolUse deny writes exactly one ``HarnessToolCallDenied`` row
carrying ``session_id``, ``tool_name``, a command/args snippet, the guard's
check id and the deny reason. A guard that allows records nothing.

These tests drive representative guards through that same sequence —
guard evaluated → identity bound → decision recorded → a real row lands in
an isolated events DB — without mocking the emit path.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from yoke_core.domain import events_crud
from yoke_core.hooks import guard_denial_identity
from yoke_core.hooks.guard_denial_record import record_guard_decision
from yoke_core.hooks.types import HookContext, HookDecision
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


def _record(module_id: str, decision: HookDecision, context: HookContext) -> HookDecision:
    """Bind and record *decision* the way the hook runner does after a guard."""
    payload = context.payload if isinstance(context.payload, dict) else {}
    command = (payload.get("tool_input") or {}).get("command") or ""
    bound = guard_denial_identity.bind(decision, module_id, command=command)
    record_guard_decision(bound, module_id, context=context)
    return bound


def _main_commit_facts(branch: str) -> dict:
    """The client's git report for a commit staging one implementation file."""
    from runtime.api.domain.test_lint_main_commit import git_facts

    return git_facts(branch, ["runtime/api/domain/foo.py"])


# ---------------------------------------------------------------------------
# Core: each denier records exactly one HarnessToolCallDenied row
# ---------------------------------------------------------------------------


class TestHarnessToolCallDeniedEndToEnd:
    def test_lint_main_commit_records_single_row_with_expected_envelope(
        self, events_db: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A lint-main-commit deny produces one row with all
        required fields (session_id, tool_name, command snippet, lint
        identifier, reason)."""
        from yoke_core.domain import lint_main_commit as lmc

        # Force the deny branch: the client reports branch main with a
        # non-bookkeeping staged path, and at least one active worktree item
        # exists. ``_active_worktree_items`` returns ``"id|title"`` strings.
        monkeypatch.setattr(
            lmc,
            "_active_worktree_items",
            lambda: ["42|Fix the thing"],
        )

        payload = {
            **_main_commit_facts("main"),
            "session_id": "sess-lmc-1",
            "tool_use_id": "tu-lmc-1",
            "tool_name": "Bash",
            "tool_input": {
                "command": "git commit -m 'implementation on main'",
            },
        }
        context = lmc._build_context_from_payload(payload)
        decision = lmc.evaluate(context)
        assert decision.block is True
        _record("yoke_core.domain.lint_main_commit", decision, context)

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
        assert detail["hook"] == "yoke_core.domain.lint_main_commit"
        assert detail["check_id"] == "impl_on_main"
        assert "command_snippet" in detail, (
            "command_snippet must be present so operators can see which "
            "call was blocked"
        )
        assert "git commit" in detail["command_snippet"]
        assert isinstance(detail["reason"], str)
        assert detail["reason"]

    def test_lint_db_cmd_records_denied_row_for_blocked_command(
        self, events_db: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """DB-command deniers share the same recording path as the other
        Python deniers. A payload the policy denies records one row under the
        stable ``lint-sqlite-cmd`` check id with the command snippet, and the
        stdin entry still prints the deny envelope."""
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
        assert '"permissionDecision": "deny"' in capsys.readouterr().out

        context = ldc._build_context_from_payload(payload)
        _record("yoke_core.domain.lint_db_cmd", ldc.evaluate(context), context)

        rows = _fetch_denials(events_db)
        assert len(rows) == 1, f"expected one denial row, got {rows}"

        envelope = json.loads(rows[0]["envelope"])
        detail = envelope["context"]["detail"]
        assert detail["hook"] == "yoke_core.domain.lint_db_cmd"
        assert detail["check_id"] == "lint-sqlite-cmd"
        assert "sqlite3" in detail["command_snippet"]
        assert envelope["event_name"] == "HarnessToolCallDenied"
        assert rows[0]["session_id"] == "sess-sqlite-1"

    def test_nested_claude_denial_and_audit_share_registered_check_id(
        self, events_db: str
    ) -> None:
        from yoke_contracts.hook_runner.hook_guard_catalog import (
            NESTED_CLAUDE_CLI_CHECK_ID,
        )
        from yoke_core.domain import lint_db_cmd as ldc

        payload = {
            "session_id": "sess-nested-claude-1",
            "tool_use_id": "tu-nested-claude-1",
            "tool_name": "Bash",
            "tool_input": {"command": 'claude -p "summarize this"'},
        }

        # A Claude caller is what makes this invocation a nesting risk, and
        # the test runner's own ancestry is not it: CI has no harness parent.
        context = dataclasses.replace(
            ldc._build_context_from_payload(payload),
            executor_family="claude-code",
        )

        decision = _record(
            "yoke_core.domain.lint_db_cmd", ldc.evaluate(context), context
        )

        assert decision.audit_fields["check_id"] == NESTED_CLAUDE_CLI_CHECK_ID
        rendered = json.loads(decision.message)["hookSpecificOutput"]
        reason = rendered["permissionDecisionReason"]
        assert f"Yoke check id: {NESTED_CLAUDE_CLI_CHECK_ID}" in reason
        assert "use the Agent tool for subagent dispatch" in reason

        rows = _fetch_denials(events_db)
        assert len(rows) == 1, f"expected one denial row, got {rows}"
        detail = json.loads(rows[0]["envelope"])["context"]["detail"]
        assert detail["hook"] == "yoke_core.domain.lint_db_cmd"
        assert detail["check_id"] == NESTED_CLAUDE_CLI_CHECK_ID
        assert "claude -p" in detail["command_snippet"]

    def test_lint_main_commit_records_nothing_when_allowed(
        self, events_db: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Happy path: no row when the lint allows the call."""
        from yoke_core.domain import lint_main_commit as lmc

        # Simulate an allow: the client reports a non-main branch.
        payload = {
            **_main_commit_facts("feature-branch"),
            "session_id": "sess-none",
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'ok'"},
        }
        context = lmc._build_context_from_payload(payload)
        _record("yoke_core.domain.lint_main_commit", lmc.evaluate(context), context)
        assert _fetch_denials(events_db) == []


# ---------------------------------------------------------------------------
# First-denier-wins semantics. Two different lints deny the same
# payload; each records exactly one row. Running them *sequentially* against
# the same payload — as the Claude PreToolUse chain would do — must not
# produce two rows for the *same* attempt. Python harness behavior already
# enforces "first denier short-circuits the chain"; Yoke's deniers only
# run when reached. This test documents the invariant by asserting that a
# sequence of deniers driven in isolation each emits its own single row
# (one recorded row per reached denier). If two reach the same payload, the
# PreToolUse harness is expected to short-circuit after the first, so only
# one row lands — consumers can trust "one HarnessToolCallDenied per
# blocked attempt" in telemetry.
# ---------------------------------------------------------------------------


class TestSingleEmitPerDenier:
    def test_each_reached_denier_records_exactly_once(
        self, events_db: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from yoke_core.domain import lint_main_commit as lmc

        monkeypatch.setattr(
            lmc,
            "_active_worktree_items",
            lambda: ["42|Fix the thing"],
        )

        payload = {
            **_main_commit_facts("main"),
            "session_id": "sess-single",
            "tool_use_id": "tu-single",
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'deny me'"},
        }
        # Invoke the single reached denier exactly once.
        context = lmc._build_context_from_payload(payload)
        _record("yoke_core.domain.lint_main_commit", lmc.evaluate(context), context)
        rows = _fetch_denials(events_db)
        assert len(rows) == 1, (
            "one reached denier must produce exactly one row per attempt "
            "(no duplicate HarnessToolCallDenied rows)"
        )
