"""Tool working directories override the hook's startup directory."""

import shlex
from unittest.mock import Mock

import pytest

from yoke_contracts.hook_runner.main_commit import CLIENT_GIT_COMMIT_FACTS_KEY
from yoke_contracts.hook_runner.repo_paths import normalize_repo_path
from yoke_contracts.hook_runner.shell_parse import parse_shell
from yoke_contracts.hook_runner.repo_paths import normalize_repo_path
from yoke_harness.hooks import local_policy_common, main_commit_client


@pytest.mark.parametrize("field", ["workdir", "working_directory"])
def test_commit_facts_use_tool_workdir(monkeypatch, field):
    payload = {"cwd": "/checkout", "tool_input": {field: "/lane"}}
    git = Mock(return_value=Mock(returncode=0, stdout="lane"))
    monkeypatch.setattr(main_commit_client, "_git", git)
    facts = main_commit_client.collect_git_commit_facts(
        payload, parse_shell("git commit -m fix")
    )
    assert local_policy_common.repo_cwd(payload) == "/lane"
    assert facts[CLIENT_GIT_COMMIT_FACTS_KEY]["repo_cwd"] == "/lane"
    assert all(call.args[0] == "/lane" for call in git.call_args_list)
    assert local_policy_common.repo_cwd(payload, "/explicit") == "/explicit"


@pytest.mark.parametrize("via", ["main", "symlink", "linked-worktree"])
def test_commit_repo_root_resolves_repository_identity(tmp_path, via):
    import subprocess

    from yoke_core.domain import lint_main_commit
    from yoke_contracts.runtime_ports import structured_dispatch
    from types import SimpleNamespace
    from unittest.mock import patch

    repo = tmp_path / "repo with spaces"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "--allow-empty", "-m", "initial")
    (repo / "source.py").write_text("value = 1\n")
    git("add", "source.py")
    cwd = repo
    command = "git commit -m change"
    if via == "symlink":
        cwd = tmp_path / "alias"
        cwd.symlink_to(repo, target_is_directory=True)
    elif via == "linked-worktree":
        cwd = repo / ".worktrees" / "lane"
        git("worktree", "add", "-b", "lane", str(cwd))
        command = f"git -C {shlex.quote(str(repo))} commit -m change"
        assert main_commit_client._repo_root(str(cwd)) == normalize_repo_path(str(repo.resolve()))
    shell = parse_shell(command)
    payload = {"cwd": str(cwd), "tool_input": {"command": command}}
    payload.update(main_commit_client.collect_git_commit_facts(payload, shell))
    assert payload[CLIENT_GIT_COMMIT_FACTS_KEY]["repo_root"] == normalize_repo_path(str(repo.resolve()))
    rows = [{"public_ref": "TEST-1", "title": "Active",
             "worktrees": [{"path": str(repo / ".worktrees" / "lane")}]}]
    dispatcher = SimpleNamespace(
        call_dispatcher=lambda **kwargs: SimpleNamespace(success=True, result={"rows": rows})
    )
    with patch.object(structured_dispatch, "get_structured_dispatch", return_value=dispatcher):
        assert lint_main_commit.evaluate_payload(payload, shell) is not None


def test_repo_root_probe_failure_has_no_identity(monkeypatch):
    monkeypatch.setattr(main_commit_client, "_git", lambda *args: None)
    assert main_commit_client._repo_root("/missing") is None
