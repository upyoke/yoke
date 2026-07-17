"""DB-command guard tests for operators, DB paths, and comparison checks."""

from __future__ import annotations

import pytest

from yoke_core.domain.lint_db_cmd import run_hook
from yoke_core.domain.lint_db_cmd_test_helpers import (
    _assert_allows,
    _assert_blocks,
)


# ---------------------------------------------------------------------------
# Check 1 — escaped operators + hardcoded DB paths + != in SQL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        'sqlite3 db.db "SELECT * FROM items WHERE id \\>= 5;"',
        'sqlite3 db.db "SELECT * FROM items WHERE id \\<= 5;"',
        'sqlite3 db.db "SELECT * FROM items WHERE id \\> 5;"',
        'sqlite3 db.db "SELECT * FROM items WHERE id \\< 5;"',
    ],
)
def test_escaped_operators_blocked(command: str) -> None:
    _assert_blocks(command)


@pytest.mark.parametrize(
    "command",
    [
        'sqlite3 data/yoke.db "SELECT * FROM items;"',
        'sqlite3 ./data/yoke.db "SELECT * FROM items;"',
        'sqlite3 yoke.db "SELECT * FROM items;"',
        'sqlite3 ./yoke.db "SELECT * FROM items;"',
        'sqlite3 -separator "|" data/yoke.db "SELECT id FROM items;"',
    ],
)
def test_hardcoded_db_paths_blocked(command: str) -> None:
    _assert_blocks(command)


@pytest.mark.parametrize(
    "command",
    [
        'sqlite3 "$YOKE_DB" "SELECT * FROM items;"',
        'sqlite3 -separator "|" "$YOKE_DB" "SELECT id FROM items;"',
        'sqlite3 /Users/foo/projects/data/yoke.db "SELECT * FROM items;"',
    ],
)
def test_all_direct_sqlite3_calls_blocked(command: str) -> None:
    _assert_blocks(command)


@pytest.mark.parametrize(
    "command",
    [
        'sqlite3 db.db "SELECT * FROM items WHERE id \\!= 5;"',
        "sqlite3 -separator \"|\" db.db \"SELECT id FROM items WHERE status \\!= 'done';\"",
    ],
)
def test_escaped_not_equal_in_sql_blocked(command: str) -> None:
    _assert_blocks(command)


# ---------------------------------------------------------------------------
# Clean operators and non-sqlite3 commands (allow path)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        'sh scripts/yoke-db.sh query "SELECT * FROM items WHERE id >= 5;"',
        'sh scripts/yoke-db.sh query "SELECT * FROM items WHERE id <= 5;"',
        'sh scripts/yoke-db.sh query "SELECT * FROM items WHERE id > 5;"',
        'sh scripts/yoke-db.sh query "SELECT * FROM items WHERE id < 5;"',
        'sh scripts/yoke-db.sh query "SELECT * FROM items WHERE id <> 5;"',
    ],
)
def test_clean_operators_via_yoke_db_allowed(command: str) -> None:
    _assert_allows(command)


@pytest.mark.parametrize(
    "command",
    [
        "echo hello world",
        'grep -q "sqlite3" somefile.sh',
        "cat README.md",
    ],
)
def test_non_sqlite_commands_allowed(command: str) -> None:
    _assert_allows(command)


# ---------------------------------------------------------------------------
# Allowlisted scripts, read-only references, compound commands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "sh .agents/skills/yoke/scripts/sqlite3-error-hook.sh",
        "sh .agents/skills/yoke/scripts/lint-sqlite-cmd.sh",
        "sh .agents/skills/yoke/scripts/migrate-to-sqlite.sh",
        "cat .agents/skills/yoke/scripts/sqlite3-error-hook.sh",
        'find . -name "*sqlite3*"',
        'rg "sqlite3" .claude/skills/',
        "git merge-tree main pg-native-runtime-sqlite3-triage-bf7c94e3",
        "git show pg-native-runtime-sqlite3-triage-bf7c94e3:runtime/api/domain/foo.py",
        "head -5 sqlite3-error-hook.sh",
        "wc -l sqlite3-error-hook.sh",
        'echo "sqlite3 is blocked by the hook"',
    ],
)
def test_yok374_allowlisted_and_read_only_references_allowed(command: str) -> None:
    _assert_allows(command)


@pytest.mark.parametrize(
    "command",
    [
        'sh migrate-to-sqlite.sh && sqlite3 db.db "SELECT * FROM items;"',
        'sh test-lint-sqlite-cmd.sh; sqlite3 "$YOKE_DB" "DROP TABLE items;"',
        'sh sqlite3-error-hook.sh || sqlite3 db.db ".tables"',
        'echo "sqlite3 db DROP TABLE items" | sh',
        'printf "sqlite3 db .tables" | bash',
        'sqlite3 "$YOKE_DB" ".read migrate-to-sqlite.sh"',
        'command sqlite3 "$YOKE_DB" "SELECT 1"',
        'env YOKE_DB=/tmp/yoke.db sqlite3 "$YOKE_DB" "SELECT 1"',
        "sh my-custom-sqlite3-tool.sh",
        "sh sqlite3-backdoor.sh",
    ],
)
def test_yok374_compound_and_bypass_attempts_blocked(command: str) -> None:
    _assert_blocks(command)


# ---------------------------------------------------------------------------
# Edge cases — fail-open on bad payloads
# ---------------------------------------------------------------------------


def test_invalid_json_payload_allows() -> None:
    assert run_hook("not json at all") == ""


def test_empty_payload_allows() -> None:
    assert run_hook("") == ""


def test_missing_command_field_allows() -> None:
    import json
    payload = json.dumps({"tool_name": "Bash", "tool_input": {}})
    assert run_hook(payload) == ""


# ---------------------------------------------------------------------------
# Shell != false-positive prevention + true positives in SQL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        '[ "$result" != "expected" ] && sh scripts/yoke-db.sh query "SELECT * FROM items WHERE status = \'done\';"',
        'result=$(sh scripts/yoke-db.sh query "SELECT COUNT(*) FROM items") && [ "$result" != "0" ]',
    ],
)
def test_shell_not_equal_outside_sql_allowed(command: str) -> None:
    _assert_allows(command)


@pytest.mark.parametrize(
    "command",
    [
        'sh scripts/yoke-db.sh query "SELECT * FROM items WHERE id \\\\>= 5;"',
        "sh scripts/yoke-db.sh query \"SELECT * FROM items WHERE status != 'done';\"",
        "sh scripts/yoke-db.sh query \"SELECT * FROM items WHERE status \\\\!= 'done';\"",
        '[ "$x" = "y" ] && sh scripts/yoke-db.sh query "SELECT * FROM items WHERE id \\\\< 5;"',
    ],
)
def test_dirty_sql_operators_blocked_via_yoke_db(command: str) -> None:
    _assert_blocks(command)
