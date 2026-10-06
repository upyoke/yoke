"""The main-write guard resolves writes where the command actually runs.

Commands here are recorded Codex ``exec_command`` bodies that the guard
refused while the call ran in the held lane, plus the Claude and Cursor
shapes of the same calls. Each one resolves against the declared workdir
and any leading ``cd``; the same bodies run on main still refuse.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_lane_main_write
from yoke_core.domain.command_workdir import command_execution_cwd

SESSION = "sid-command-workdir"
ITEM_ID = 2729

# Computed ``p.write_text`` destinations relative to the running directory.
COMPUTED_EDIT = (
    "python3 - <<'PY'\n"
    "from pathlib import Path\n"
    "def change(name, old, new):\n"
    " p=Path(name); s=p.read_text(); assert old in s,name; "
    "p.write_text(s.replace(old,new))\n"
    "c='packages/yoke-core/src/yoke_core/domain/'\n"
    "change(c+'projects_restart_schema.py','a\\n','b\\n')\n"
    "PY"
)
# A relative heredoc redirect target.
RELATIVE_HEREDOC = (
    "cat > runtime/api/dashboard_wrapping_rows.visual.mjs <<'EOF'\n"
    'import assert from "node:assert/strict";\n'
    "EOF"
)
# A temp-file capture whose destination is a computed ``open(f.name)``.
TEMPFILE_CAPTURE = (
    "python3 - <<'PY'\n"
    "import json,subprocess,tempfile\n"
    "f=tempfile.NamedTemporaryFile(prefix='yoke-cmd.',dir='/tmp',delete=False)\n"
    "f.close()\n"
    "with open(f.name,'w') as out:\n"
    " r=subprocess.run(['yoke','qa','artifact','read'],stdout=out)\n"
    "PY"
)
RECORDED = (COMPUTED_EDIT, RELATIVE_HEREDOC, TEMPFILE_CAPTURE)


@pytest.fixture
def lane_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees").mkdir(parents=True)
    with test_database() as conn:
        register_machine_checkout(tmp_path / "machine-config", repo, project_id=1)
        seed_item(
            conn,
            item_id=ITEM_ID,
            branch=f"YOK-{ITEM_ID}",
            status="implementing",
            repo_path=repo,
        )
        seed_item_claim(conn, SESSION, item_id=ITEM_ID)
        lane = repo / ".worktrees" / f"YOK-{ITEM_ID}"
        lane.mkdir(parents=True)
        yield repo, lane


def _evaluate(command: str, *, cwd: Path, **extra):
    tool_input = {"command": command, **extra.pop("tool_input", {})}
    payload = {
        "session_id": SESSION,
        "tool_name": "Bash",
        "cwd": str(cwd),
        "tool_input": tool_input,
        **extra,
    }
    with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
        return lint_lane_main_write.evaluate_pre_tool_use(payload)


@pytest.mark.parametrize("command", RECORDED)
def test_codex_declared_lane_workdir_allows(lane_repo, command):
    repo, lane = lane_repo
    verdict = _evaluate(command, cwd=repo, tool_input={"workdir": str(lane)})
    assert verdict.allow is True, verdict.reason


@pytest.mark.parametrize("separator", ["\n", " && ", "; "])
@pytest.mark.parametrize("command", RECORDED)
def test_leading_cd_into_lane_allows(lane_repo, command, separator):
    repo, lane = lane_repo
    verdict = _evaluate(f"cd {lane}{separator}{command}", cwd=repo)
    assert verdict.allow is True, verdict.reason


@pytest.mark.parametrize("command", RECORDED)
def test_claude_lane_cwd_allows(lane_repo, command):
    _repo, lane = lane_repo
    assert _evaluate(command, cwd=lane).allow is True


@pytest.mark.parametrize("command", RECORDED)
def test_cursor_working_directory_allows(lane_repo, command):
    repo, lane = lane_repo
    verdict = _evaluate(command, cwd=repo, working_directory=str(lane))
    assert verdict.allow is True, verdict.reason


@pytest.mark.parametrize("command", (COMPUTED_EDIT, RELATIVE_HEREDOC))
def test_same_writes_on_main_still_deny(lane_repo, command):
    repo, lane = lane_repo
    assert _evaluate(command, cwd=repo).allow is False
    assert (
        _evaluate(command, cwd=lane, tool_input={"workdir": str(repo)}).allow is False
    )
    assert _evaluate(f"cd {repo}\n{command}", cwd=lane).allow is False


def test_cd_out_of_the_lane_follows_the_shell(lane_repo):
    repo, lane = lane_repo
    verdict = _evaluate(f"cd {lane} && cd ../..\n{COMPUTED_EDIT}", cwd=repo)
    assert verdict.allow is False
    assert verdict.attempted_path == str(repo.resolve())


def test_unreadable_cd_keeps_the_last_readable_directory(lane_repo):
    repo, _lane = lane_repo
    verdict = _evaluate(f'cd "$LANE"\n{COMPUTED_EDIT}', cwd=repo)
    assert verdict.allow is False


@pytest.mark.parametrize("command", (COMPUTED_EDIT, RELATIVE_HEREDOC))
def test_the_denials_own_recoveries_pass_the_guard(lane_repo, command):
    repo, lane = lane_repo
    denied = _evaluate(command, cwd=repo)
    assert denied.allow is False
    reason = denied.reason
    if "declare " in reason:
        workdir = re.search(r"declare (\S+) as the call's workdir", reason).group(1)
        cd_target = re.search(r"make `cd (\S+)` the command's first", reason).group(1)
        assert _evaluate(command, cwd=repo, tool_input={"workdir": workdir}).allow
        assert _evaluate(f"cd {cd_target}\n{command}", cwd=repo).allow
    else:
        in_lane = re.search(r"Use instead:\s+(\S+)", reason).group(1)
        rewritten = command.replace(
            "runtime/api/dashboard_wrapping_rows.visual.mjs",
            in_lane,
        )
        assert _evaluate(rewritten, cwd=repo).allow


def test_resolver_walks_relative_cd_from_the_declared_workdir(tmp_path):
    payload = {
        "cwd": "/session",
        "tool_input": {
            "command": "cd sub; cd deeper\ntouch x",
            "workdir": str(tmp_path),
        },
    }
    assert command_execution_cwd(payload) == str(
        (tmp_path / "sub" / "deeper").resolve()
    )


def test_resolver_ignores_a_cd_after_the_first_command(tmp_path):
    payload = {
        "cwd": str(tmp_path),
        "tool_input": {"command": "touch x && cd /elsewhere"},
    }
    assert command_execution_cwd(payload) == str(tmp_path.resolve())
