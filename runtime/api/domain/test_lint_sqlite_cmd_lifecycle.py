"""DB-command guard tests for lifecycle writes, DDL, raw body, items add, main.

Kept under the legacy ``test_lint_sqlite_cmd*.py`` filename glob for stable
verification while importing the neutral DB-command runner/helper except when
testing the legacy compatibility module directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import lint_sqlite_cmd as lint_mod
from yoke_core.domain.lint_db_cmd import run_hook
from yoke_core.domain.lint_db_cmd_test_helpers import (
    _assert_allows,
    _assert_blocks,
    _fresh_live_db,
    _payload,
)


# ---------------------------------------------------------------------------
# Check 9 — direct status=done writes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "YOKE_FORCE=1 sh scripts/yoke-db.sh items update 42 status done # lint:no-done-check",
        "export YOKE_FORCE=1; sh scripts/backlog-registry.sh update 42 status done # lint:no-done-check",
        "YOKE_FORCE=1 sh .agents/skills/yoke/scripts/done-transition.sh 42 --skip-deploy",
        "YOKE_DONE_RECOVERY=1 sh scripts/yoke-db.sh items update 42 status done # lint:no-done-check",
        "export YOKE_DONE_RECOVERY=1; sh scripts/backlog-registry.sh update 42 status done # lint:no-done-check",
        "sh scripts/yoke-db.sh items update 42 status done",
        "sh scripts/backlog-registry.sh update 42 status done",
        "sh .agents/skills/yoke/scripts/yoke-db.sh items update 42 status done",
    ],
)
def test_yok950_direct_done_writes_blocked(command: str) -> None:
    _assert_blocks(command)


@pytest.mark.parametrize(
    "command",
    [
        "sh scripts/yoke-db.sh items update 42 status done # lint:no-done-check",
        "sh scripts/yoke-db.sh items update 42 status active",
        "sh scripts/yoke-db.sh items update 42 status passed",
        "sh scripts/yoke-db.sh query \"SELECT id FROM items WHERE status='done'\"",
    ],
)
def test_yok950_done_suppression_and_non_done_transitions_allowed(command: str) -> None:
    _assert_allows(command)


# ---------------------------------------------------------------------------
# Check 12 removed (status=passed no longer blocked)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "sh scripts/yoke-db.sh items update 42 status passed",
        "sh .agents/skills/yoke/scripts/yoke-db.sh items update 42 status passed",
        "sh scripts/yoke-db.sh items update 42 status passed # lint:no-passed-check",
        "sh scripts/yoke-db.sh query \"SELECT id FROM items WHERE status='passed'\"",
        "sh scripts/yoke-db.sh items update 42 status review",
    ],
)
def test_yok1055_status_passed_no_longer_blocked(command: str) -> None:
    _assert_allows(command)


def test_yok1055_backlog_registry_still_guarded() -> None:
    # Guarded-script rule still catches backlog-registry.sh, regardless of status.
    _assert_blocks("sh scripts/backlog-registry.sh update 42 status passed")


# ---------------------------------------------------------------------------
# Check 11 — DDL advisory in yoke-db.sh query
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        'sh scripts/yoke-db.sh query "ALTER TABLE foo ADD COLUMN bar TEXT"',
        'sh scripts/yoke-db.sh query "CREATE TABLE foo (id INTEGER)"',
        'sh scripts/yoke-db.sh query "DROP TABLE foo"',
    ],
)
def test_yok1026_ddl_in_query_blocked(command: str) -> None:
    _assert_blocks(command)


@pytest.mark.parametrize(
    "command",
    [
        'sh scripts/yoke-db.sh query "ALTER TABLE foo ADD COLUMN bar TEXT" # lint:no-ddl-check',
        'sh scripts/yoke-db.sh query "SELECT * FROM items"',
        "sh scripts/yoke-db.sh items update 42 status active",
    ],
)
def test_yok1026_ddl_suppression_and_unaffected_commands(command: str) -> None:
    _assert_allows(command)


# ---------------------------------------------------------------------------
# Raw body writes blocked with no bypass
# ---------------------------------------------------------------------------


def test_yok1323_raw_body_writes_always_blocked() -> None:
    # Structured item (has spec) — blocked.
    decision = _assert_blocks(
        'sh "$SCRIPT_DIR/yoke-db.sh" items update YOK-9999 body --body-file "$_tmp_body"',
    )
    assert "Raw body writes are no longer supported" in decision["permissionDecisionReason"]

    # Body-only item — still blocked.
    _assert_blocks(
        'sh "$SCRIPT_DIR/yoke-db.sh" items update 43 body --body-file "$_tmp_body"',
    )

    # Old bypass comment is inert.
    _assert_blocks(
        'sh "$SCRIPT_DIR/yoke-db.sh" items update 44 body --body-file "$_tmp_body" # lint:no-body-write-check',
    )


# ---------------------------------------------------------------------------
# Check 14 — items add without --project emits advisory
# ---------------------------------------------------------------------------


def test_yok1158_items_add_without_project_emits_allow_advisory() -> None:
    output = run_hook(
        _payload('sh scripts/yoke-db.sh items add "Missing project" issue idea medium')
    )
    assert output, "expected advisory output"
    decision = json.loads(output)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "allow", (
        f"expected advisory ALLOW, got: {output!r}"
    )


def test_yok1158_items_add_with_project_silent() -> None:
    assert (
        run_hook(
            _payload(
                'sh scripts/yoke-db.sh items add --project yoke "Has project" issue idea medium'
            )
        )
        == ""
    )


def test_yok1158_items_add_suppression_silent() -> None:
    assert (
        run_hook(
            _payload(
                'sh scripts/yoke-db.sh items add "Suppressed" issue idea medium # lint:no-project-check'
            )
        )
        == ""
    )


# ---------------------------------------------------------------------------
# Canonical DB fallback for bare launcher
# ---------------------------------------------------------------------------


class _StdinStub:
    """Tiny file-like stub that returns a fixed payload for ``sys.stdin``.

    The lint CLI reads stdin once via ``sys.stdin.read()``; a full
    StringIO-based fake is overkill and triggers pytest-capture
    interactions. This minimal stub matches the interface the CLI
    actually touches.
    """

    def __init__(self, payload: str) -> None:
        self._payload = payload

    def read(self) -> str:
        return self._payload


def test_yok1384_main_without_yoke_db_env_falls_back_to_canonical(
    tmp_path: Path, monkeypatch
) -> None:
    """Legacy ``lint_sqlite_cmd.main()`` resolves the canonical DB fallback
    when ``YOKE_DB`` is unset.

    Prior to the tracked-launcher fix the Claude PreToolUse launcher injected
    ``YOKE_DB="${CLAUDE_PROJECT_DIR:-$PWD}/data/yoke.db"`` which
    resolved to ``.worktrees/<branch>/data/yoke.db`` inside a linked
    worktree — silently bypassing the Python resolver. The launcher now
    runs the bare module, so ``main()`` must hydrate YOKE_DB from the
    canonical resolver before delegating into run_hook. The resolver is
    stubbed here to a fresh temp DB so the test does not depend on the
    repo layout.
    """
    db_path = _fresh_live_db(tmp_path)
    monkeypatch.delenv("YOKE_DB", raising=False)
    monkeypatch.setattr(lint_mod, "_resolve_db_fallback", lambda: db_path)

    captured: dict[str, str] = {}
    original_run_hook = lint_mod.run_hook

    def spy_run_hook(payload: str, yoke_db: str = "") -> str:
        captured["yoke_db"] = yoke_db
        return original_run_hook(payload, yoke_db=yoke_db)

    monkeypatch.setattr(lint_mod, "run_hook", spy_run_hook)
    monkeypatch.setattr(
        "sys.stdin",
        _StdinStub(_payload("sqlite3 '$YOKE_DB' 'SELECT 1'")),
    )

    rc = lint_mod.main()
    assert rc == 0
    assert captured["yoke_db"] == db_path, (
        "legacy lint_sqlite_cmd.main() must pass the canonical DB path into "
        "run_hook when YOKE_DB is unset (YOK-1384)"
    )


def test_yok1384_main_prefers_yoke_db_env_when_set(
    tmp_path: Path, monkeypatch
) -> None:
    """Programmatic callers (Codex, tests) still win via the env var —
    the canonical DB fallback must only engage when YOKE_DB is unset."""
    explicit_db = _fresh_live_db(tmp_path)
    monkeypatch.setenv("YOKE_DB", explicit_db)

    fallback_called = {"hit": False}

    def fake_fallback() -> str:
        fallback_called["hit"] = True
        return str(tmp_path / "should-not-be-used.db")

    monkeypatch.setattr(lint_mod, "_resolve_db_fallback", fake_fallback)

    captured: dict[str, str] = {}
    original_run_hook = lint_mod.run_hook

    def spy_run_hook(payload: str, yoke_db: str = "") -> str:
        captured["yoke_db"] = yoke_db
        return original_run_hook(payload, yoke_db=yoke_db)

    monkeypatch.setattr(lint_mod, "run_hook", spy_run_hook)
    monkeypatch.setattr(
        "sys.stdin", _StdinStub(_payload("echo hello"))
    )

    rc = lint_mod.main()
    assert rc == 0
    assert captured["yoke_db"] == explicit_db
    assert fallback_called["hit"] is False, (
        "legacy lint_sqlite_cmd.main() must not consult the Python resolver when "
        "YOKE_DB is already set"
    )


def test_yok1384_resolve_db_fallback_degrades_silently(monkeypatch) -> None:
    """``_resolve_db_fallback`` must never raise — lint hooks are
    fail-open. A resolver failure must return ``""`` so run_hook falls
    back to the static policy path."""

    def explode() -> str:
        raise RuntimeError("simulated resolver failure")

    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.resolve_db_path", explode
    )
    assert lint_mod._resolve_db_fallback() == ""
