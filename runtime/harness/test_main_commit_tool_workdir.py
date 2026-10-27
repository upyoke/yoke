"""Tool working directories override the hook's startup directory."""

from unittest.mock import Mock

import pytest

from yoke_contracts.hook_runner.main_commit import CLIENT_GIT_COMMIT_FACTS_KEY
from yoke_contracts.hook_runner.shell_parse import parse_shell
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
