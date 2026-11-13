"""Client-side directory facts follow the command's real directory.

Note 95936: a ``git commit`` after a leading ``cd`` reads the repository it
runs in. Note 93733: a Codex ``exec_command`` whose ``workdir`` is a bound
identifier stamps that directory.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from yoke_contracts.hook_runner.main_commit import CLIENT_GIT_COMMIT_FACTS_KEY
from yoke_contracts.hook_runner.shell_parse import parse_shell
from yoke_harness.hooks import main_commit_client
from yoke_harness.hooks.command_workdir_stamp import (
    exec_command_calls,
    workdir_for_command,
)

MAIN = "/checkout"
LANE = "/checkout/.worktrees/YOK-1"


def _commit_cwd(monkeypatch, command: str, workdir: str = "") -> str:
    payload = {"cwd": MAIN, "tool_input": {"command": command}}
    if workdir:
        payload["tool_input"]["workdir"] = workdir
    git = Mock(return_value=Mock(returncode=0, stdout="branch"))
    monkeypatch.setattr(main_commit_client, "_git", git)
    facts = main_commit_client.collect_git_commit_facts(payload, parse_shell(command))
    cwd = facts[CLIENT_GIT_COMMIT_FACTS_KEY]["repo_cwd"]
    assert all(call.args[0] == cwd for call in git.call_args_list)
    return cwd


def test_commit_after_cd_reads_the_lane(monkeypatch):
    assert _commit_cwd(monkeypatch, f"cd {LANE} && git commit -m fix") == (
        str(Path(LANE).resolve())
    )


def test_commit_after_cd_to_tmp_reads_tmp(monkeypatch):
    command = "cd /tmp/scratch && git add a && git commit -m fix"
    assert _commit_cwd(monkeypatch, command) == str(Path("/tmp/scratch").resolve())


def test_plain_commit_on_main_reads_main(monkeypatch):
    assert _commit_cwd(monkeypatch, "git commit -m fix") == MAIN


def test_commit_after_hopping_back_to_main_reads_main(monkeypatch):
    command = f"cd {LANE} && cd {MAIN} && git commit -m fix"
    assert _commit_cwd(monkeypatch, command) == str(Path(MAIN).resolve())


def test_commit_after_unreadable_cd_keeps_the_payload_cwd(monkeypatch):
    assert _commit_cwd(monkeypatch, "cd $UNKNOWN && git commit -m fix") == MAIN


def test_git_c_still_wins_over_cd(monkeypatch):
    command = f"cd /tmp && git -C {LANE} commit -m fix"
    assert _commit_cwd(monkeypatch, command) == LANE


def test_commit_uses_the_declared_workdir_as_base(monkeypatch):
    assert _commit_cwd(monkeypatch, "git commit -m fix", workdir=LANE) == LANE


def _exec(body: str, cmd: str = "touch f.py") -> str:
    return f'text(await tools.exec_command({{cmd:"{cmd}",workdir:{body}}}));'


def test_identifier_workdir_resolves_from_its_single_binding():
    source = f'const cwd = "{LANE}";\n' + _exec("cwd")
    assert exec_command_calls(source) == [{"cmd": "touch f.py", "workdir": LANE}]
    assert workdir_for_command(source, "touch f.py") == LANE


@pytest.mark.parametrize("keyword", ["let", "var"])
def test_let_and_var_bindings_resolve(keyword):
    source = f"{keyword} dir = '{LANE}';\n" + _exec("dir")
    assert workdir_for_command(source, "touch f.py") == LANE


@pytest.mark.parametrize(
    "prelude",
    [
        f'const cwd = "{LANE}";\nconst cwd2 = "x";\nlet cwd = "{MAIN}";\n',
        f'let cwd = "{LANE}";\ncwd = "{MAIN}";\n',
        f'let cwd = "{LANE}";\ncwd += "/sub";\n',
        f"let cwd = `{LANE}/${{name}}`;\n",
        "const cwd = pickDirectory();\n",
        "",
    ],
    ids=["two-bindings", "reassigned", "compound", "template", "call", "unbound"],
)
def test_ambiguous_identifier_workdir_stamps_nothing(prelude):
    source = prelude + _exec("cwd")
    assert exec_command_calls(source) == [{"cmd": "touch f.py", "workdir": None}]
    assert workdir_for_command(source, "touch f.py") == ""


def test_literal_workdir_on_main_still_stamps_main():
    source = f'const cwd = "{LANE}";\n' + _exec(f'"{MAIN}"')
    assert workdir_for_command(source, "touch f.py") == MAIN


def test_object_property_does_not_count_as_a_binding():
    source = f'const cwd = "{LANE}";\nopts.cwd = "{MAIN}";\n' + _exec("cwd")
    assert workdir_for_command(source, "touch f.py") == LANE
