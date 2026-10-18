"""The main-write guard resolves writes where the command actually runs.

Commands here are recorded Codex ``exec_command`` bodies that the guard
refused while the call ran in the held lane, plus the Claude and Cursor
shapes of the same calls. Each one resolves against the declared workdir
and any leading ``cd``; the same bodies run on main still refuse.
"""

from __future__ import annotations

import re
import json
from pathlib import Path
from unittest import mock

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.hook_runner.client_facts import WRITE_TARGETS_KEY, client_fact
from yoke_core.domain import lint_lane_main_write
from yoke_core.domain.command_workdir import command_execution_cwd
from yoke_harness.hooks.client_write_targets import execution_cwd
from yoke_harness.hooks.command_workdir_stamp import stamp_command_workdir

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


RELATIVE_TARGET = "runtime/api/dashboard_wrapping_rows.visual.mjs"


def test_client_answer_from_the_wrong_directory_cannot_move_a_lane_write(lane_repo):
    """A client that missed the newline ``cd`` named main; the server's cwd wins."""
    repo, lane = lane_repo
    stale = client_fact(
        WRITE_TARGETS_KEY,
        {
            "paths": {RELATIVE_TARGET: {"path": str(repo / RELATIVE_TARGET)}},
            "worktrees": [str(lane)],
        },
    )
    verdict = _evaluate(f"cd {lane}\n{RELATIVE_HEREDOC}", cwd=repo, **stale)
    assert verdict.allow is True, verdict.reason


def test_client_answer_that_agrees_still_refuses_on_main(lane_repo):
    repo, _lane = lane_repo
    agreeing = client_fact(
        WRITE_TARGETS_KEY,
        {"paths": {RELATIVE_TARGET: {"path": str(repo.resolve() / RELATIVE_TARGET)}}},
    )
    assert _evaluate(RELATIVE_HEREDOC, cwd=repo, **agreeing).allow is False


@pytest.mark.parametrize("separator", ["\n", " && ", "; ", " &&\n"])
def test_client_walks_a_leading_cd_across_every_separator(tmp_path, separator):
    payload = {
        "cwd": "/session",
        "tool_input": {"command": f"cd {tmp_path}{separator}{RELATIVE_HEREDOC}"},
    }
    assert execution_cwd(payload) == str(tmp_path.resolve())


def test_real_codex_rollout_workdir_reaches_the_guard(lane_repo, tmp_path):
    repo, lane = lane_repo
    transcript = tmp_path / "rollout.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-command",
                    "arguments": json.dumps(
                        {"cmd": COMPUTED_EDIT, "workdir": str(lane)}
                    ),
                }
            }
        )
        + "\n"
    )
    original = {
        "cwd": str(repo),
        "tool_input": {"command": COMPUTED_EDIT},
        "transcript_path": str(transcript),
        "tool_use_id": "call-command",
    }
    stamped = json.loads(stamp_command_workdir(json.dumps(original), "codex"))
    assert _evaluate(COMPUTED_EDIT, cwd=repo, tool_input=stamped["tool_input"]).allow
    assert not _evaluate(COMPUTED_EDIT, cwd=repo).allow


@pytest.mark.parametrize(
    "body",
    [
        "import tempfile\nfrom pathlib import Path\nwith tempfile.TemporaryDirectory() as root:\n (Path(root) / 'result').write_text('x')",
        "import tempfile\nfrom pathlib import Path\nroot=tempfile.mkdtemp()\n(Path(root) / 'result').write_text('x')",
        "from pathlib import Path\nprefix='/tmp/capture-'\nPath(prefix + filename).write_text('x')",
    ],
)
def test_temporary_computed_write_from_main_allows(lane_repo, body):
    repo, _lane = lane_repo
    command = f"python3 - <<'PY'\n{body}\nPY"
    assert _evaluate(command, cwd=repo).allow
    main_write = f"\nPath({str(repo / 'source.py')!r}).write_text('x')"
    mixed = f"python3 - <<'PY'\n{body}{main_write}\nPY"
    assert not _evaluate(mixed, cwd=repo).allow
