"""DB-command guard tests for CLI, scripts, awk, heredocs, and Python."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.hook_runner import lint_policy
from yoke_core.domain import lint_config
from yoke_core.domain.lint_db_cmd import run_hook
from yoke_core.domain.lint_db_cmd_test_helpers import (
    _assert_allows,
    _assert_blocks,
    _payload,
)


# ---------------------------------------------------------------------------
# Worktree-local DB path guessing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        'ugrep -n "modules_dir" /Users/example/yoke/.worktrees/feature-branch/data/yoke.db',
        "grep x .worktrees/work-branch/data/yoke.db",
        "YOKE_DB=$PWD/data/yoke.db python3 -m yoke_core.cli.db_router items list",
        "YOKE_DB=${PWD}/data/yoke.db python3 -m yoke_core.cli.db_router items list",
        "YOKE_DB=$CLAUDE_PROJECT_DIR/data/yoke.db python3 -m yoke_core.cli.db_router items list",
    ],
)
def test_worktree_local_yoke_db_paths_blocked(command: str) -> None:
    _assert_blocks(command)


@pytest.mark.parametrize(
    "command",
    [
        "python3 -m yoke_core.domain.worktree paths db",
        "python3 -m yoke_core.cli.db_router items list",
        'rg "\\\\.worktrees/.*/data/yoke\\\\.db" runtime',
        "YOKE_DB=/tmp/test.db python3 -m yoke_core.cli.db_router items list",
    ],
)
def test_resolved_or_noncanonical_db_paths_allowed(command: str) -> None:
    _assert_allows(command)


# ---------------------------------------------------------------------------
# Check 5 — claude CLI invocations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        'claude -p "summarize this"',
        'claude --print "summarize this"',
        'claude -c "do something"',
        "claude",
        'echo foo | claude -p "summarize"',
        "cat file.txt | claude --print",
        'echo test && claude -p "hello"',
        'echo test; claude -p "hello"',
        '/usr/local/bin/claude -p "hello"',
        'FOO=bar claude -p "hello"',
    ],
)
def test_yok367_claude_cli_invocations_blocked(command: str) -> None:
    _assert_blocks(command)


def _write_lint_config(tmp_path, text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "lint-config"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(lint_config, "config_path", lambda root=None: str(path))
    lint_config.reset_cache()


def test_yok367_remote_ssh_claude_cli_denied_by_default(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pin an empty lint-config so the CATALOG default (deny) is exercised. The
    # operator's repo .yoke/lint-config opts this guard down to warn, which must
    # not leak into the default-behavior assertion (the warn path is covered by
    # test_yok367_remote_ssh_claude_cli_warn_allows).
    _write_lint_config(tmp_path, "", monkeypatch)
    _assert_blocks(
        "ssh testy@100.117.161.86 "
        "'/bin/zsh -lic '\\''if command -v claude >/dev/null; "
        "then claude --version; fi'\\'''"
    )


def test_yok367_remote_ssh_claude_cli_warn_allows(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_lint_config(
        tmp_path, f"{lint_config.REMOTE_CLAUDE_CLI_GUARD}=warn\n", monkeypatch
    )
    _assert_allows(
        "ssh testy@100.117.161.86 "
        "'/bin/zsh -lic '\\''if command -v claude >/dev/null; "
        "then claude -p \"Say CLAUDE_MAC_SMOKE_OK\"; fi'\\'''"
    )


def test_remote_ssh_claude_cli_payload_snapshot_allows(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_lint_config(tmp_path, "", monkeypatch)
    command = (
        "ssh testy@100.117.161.86 "
        "'/bin/zsh -lic '\\''claude -p \"Say CLAUDE_MAC_SMOKE_OK\"'\\'''"
    )
    data = json.loads(_payload(command))
    data[lint_policy.SNAPSHOT_PAYLOAD_KEY] = {
        lint_config.REMOTE_CLAUDE_CLI_GUARD: {"mode": "warn"},
    }

    assert run_hook(json.dumps(data)) == ""


def test_yok367_remote_warn_does_not_allow_local_claude(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_lint_config(
        tmp_path, f"{lint_config.REMOTE_CLAUDE_CLI_GUARD}=warn\n", monkeypatch
    )
    _assert_blocks("ssh testy@100.117.161.86 true; claude -p hello")


@pytest.mark.parametrize(
    "command",
    [
        "cat .agents/skills/yoke/scripts/lint-sqlite-cmd.sh",
        "sh .agents/skills/yoke/scripts/yoke-db.sh items list",
        "ls .claude/agents/",
        'grep -r "pattern" .claude/skills/',
        "head -5 .claude/rules/session.md",
        'echo "claude is an AI assistant"',
        'git commit -m "fix claude agent config"',
        'grep "claude" README.md',
    ],
)
def test_yok367_claude_in_strings_paths_allowed(command: str) -> None:
    _assert_allows(command)


# ---------------------------------------------------------------------------
# Check 3 — guarded scripts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        'sh backlog-registry.sh add "new item"',
        'sh .agents/skills/yoke/scripts/backlog-registry.sh add "item"',
        "sh sprint-db.sh start SPRINT1",
        "sh merge-worktree.sh YOK-9999",
        'FOO=bar sh backlog-registry.sh add "item"',
        "echo done && sh sprint-db.sh start",
        'echo done; sh backlog-registry.sh add "item"',
    ],
)
def test_yok491_guarded_scripts_blocked(command: str) -> None:
    _assert_blocks(command)


@pytest.mark.parametrize(
    "command",
    [
        "git add backlog-registry.sh",
        "git diff sprint-db.sh",
        "git diff -- backlog-registry.sh",
        'git commit -m "Fixed backlog-registry.sh issue"',
        'git commit -m "Updated sprint-db.sh to fix merge"',
        'git commit -m "Refactored merge-worktree.sh"',
        'grep -n "something" backlog-registry.sh',
        "cat backlog-registry.sh",
        "head -5 sprint-db.sh",
        "wc -l merge-worktree.sh",
        "ls -la backlog-registry.sh sprint-db.sh",
        "diff backlog-registry.sh sprint-db.sh",
    ],
)
def test_yok491_guarded_script_non_invocation_allowed(command: str) -> None:
    _assert_allows(command)


@pytest.mark.parametrize(
    "command",
    [
        "sh merge-worktree.sh YOK-9999 # lint:no-guard-check",
        "sh .agents/skills/yoke/scripts/merge-worktree.sh YOK-9999 # lint:no-guard-check",
        'sh backlog-registry.sh add "item" # lint:no-guard-check',
        "sh sprint-db.sh start SPRINT1 # lint:no-guard-check",
    ],
)
def test_yok849_guard_suppression_allows(command: str) -> None:
    _assert_allows(command)


def test_yok849_suppression_is_scoped_to_guard_check() -> None:
    _assert_blocks("sh merge-worktree.sh YOK-9999")


def test_yok491_env_var_bypass_blocked() -> None:
    _assert_blocks('YOKE_SKILL_CONTEXT=idea sh backlog-registry.sh add "item"')


@pytest.mark.parametrize(
    "command",
    [
        'grep "YOKE_SKILL_CONTEXT=" backlog-registry.sh',
        'echo "YOKE_SKILL_CONTEXT= is used for skill routing"',
        'git commit -m "remove YOKE_SKILL_CONTEXT= env var bypass"',
    ],
)
def test_yok491_env_var_pattern_in_prose_allowed(command: str) -> None:
    _assert_allows(command)


# ---------------------------------------------------------------------------
# Check 4 — awk negation (BSD incompatibility)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "awk '{if (!skip) print}' file.txt",
        "awk 'NR>1 && !header{print}' data.csv",
    ],
)
def test_yok491_bsd_awk_negation_blocked(command: str) -> None:
    _assert_blocks(command)


@pytest.mark.parametrize(
    "command",
    [
        "awk '{if (skip==0) print}' file.txt",
        "awk 'NR>1{print}' data.csv",
        "echo hello world",
    ],
)
def test_yok491_safe_awk_patterns_allowed(command: str) -> None:
    _assert_allows(command)


# ---------------------------------------------------------------------------
# Heredoc stripping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        'cat << EOF\nimport sqlite3\nconn = sqlite3.connect("test.db")\nEOF',
        "cat << EOF\nThe sqlite3 module is used for DB access.\nEOF",
        'cat << EOF\nsh backlog-registry.sh add "example"\nEOF',
        "cat << EOF\nThe sprint-db.sh script manages sprint data.\nEOF",
        "cat << 'EOF'\nsh merge-worktree.sh YOK-9999\nEOF",
        "cat << EOF\nYOKE_SKILL_CONTEXT= is an env var used for routing\nEOF",
        "cat << 'NOTE' | sh yoke-db.sh epic review-insert 823 005\nsqlite3 should stay inside the heredoc\nNOTE",
        "cat << EOF > /tmp/heredoc.out\nsqlite3 should stay inside the heredoc\nEOF",
        "cat <<'NOTE' | sh yoke-db.sh epic progress-note-insert 985 4 1\nsqlite3 is used for DB access\nNOTE",
        "cat <<'NOTE' | sh yoke-db.sh epic progress-note-insert 985 4 1\nsh backlog-registry.sh add example\nNOTE",
        "cat <<EOF > /tmp/file\nimport sqlite3\nEOF",
        "cat <<EOF # this is a comment\nimport sqlite3\nEOF",
        "cat <<-EOF | sh yoke-db.sh epic progress-note-insert 985 4 1\n\timport sqlite3\n\tEOF",
        "cat << EOF\ngh issue view 42\nEOF",
    ],
)
def test_heredoc_body_is_stripped(command: str) -> None:
    _assert_allows(command)


@pytest.mark.parametrize(
    "command",
    [
        "cat <<EOF | sh backlog-registry.sh add\nhello world\nEOF",
        "cat <<-EOF | sh backlog-registry.sh add\n\thello world\n\tEOF",
        'cat << EOF\nhello world\nEOF\nsqlite3 db.db "SELECT 1"',
        "cat << 'EOF' | sqlite3 db.db \"SELECT 1\"\nhello world\nEOF",
        "cat << 'EOF' | sh backlog-registry.sh add \"item\"\nhello world\nEOF",
    ],
)
def test_heredoc_opener_preserves_later_checks(command: str) -> None:
    _assert_blocks(command)


# ---------------------------------------------------------------------------
# Python literal DB path safety
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "python3 - <<'PY'\nimport sqlite3\nconn = sqlite3.connect(\"yoke.db\")\nPY",
        'python3 -c "import sqlite3; sqlite3.connect(\\"yoke.db\\")"',
        "python3 - <<'PY'\nimport os, sqlite3\ndb_path = os.path.join(\"/tmp\", \"yoke.db\")\nconn = sqlite3.connect(db_path)\nPY",
    ],
)
def test_python_literal_yoke_db_blocked(command: str) -> None:
    _assert_blocks(command)


def test_python_resolved_db_via_argv_allowed() -> None:
    command = (
        "YOKE_DB=/tmp/test.db python3 - \"$YOKE_DB\" <<'PY'\n"
        "import sqlite3, sys\n"
        "conn = sqlite3.connect(sys.argv[1])\n"
        "PY"
    )
    _assert_allows(command)
