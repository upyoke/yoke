"""Git hook refusals must stop before dirt classification and cleanup."""

from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest

from yoke_core.engines import merge_worktree as mw
from yoke_core.engines.merge_worktree_prepare_state import _pre_merge_integration
from yoke_core.engines.merge_worktree_rebase import do_rebase_or_merge
from yoke_core.engines.merge_worktree_context import MergeArgs, MergeContext


@pytest.mark.parametrize("generated_conflict", [False, True])
def test_integration_reports_hook_refusal(monkeypatch, generated_conflict):
    ctx = MergeContext(args=MergeArgs(branch="integration"), worktree_path="/lane")
    commands = []

    def git(cmd, **kw):
        commands.append(cmd)
        if cmd[0] == "merge-base":
            return CompletedProcess(cmd, 0, "base", "")
        if cmd[0] == "rev-list":
            return CompletedProcess(cmd, 0, "1", "")
        if cmd[0] in {"merge", "commit"}:
            return CompletedProcess(cmd, 1, "", "authored-file-limit: 351 > 350")
        if cmd[0] == "diff":
            return CompletedProcess(
                cmd, 0, ".yoke/BOARD.md" if generated_conflict else "", ""
            )
        return CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mw, "_run_git", git)
    emit = Mock()
    monkeypatch.setattr(mw, "_print", emit)
    result = _pre_merge_integration(ctx)
    assert result[0] == 1
    assert "merge_integration_refused" in result[1]
    assert "authored-file-limit" in result[1]
    assert "complete the pending merge" in result[1]
    assert not any(cmd[0] == "stash" for cmd in commands)
    assert not any("success" in str(call) for call in emit.call_args_list)


def test_merge_fallback_checks_commit_hook(monkeypatch):
    ctx = MergeContext(args=MergeArgs(branch="integration", source_sha="a" * 40))
    monkeypatch.setattr(
        "yoke_core.domain.project_settings.get_project_int", lambda *a: 2
    )
    monkeypatch.setattr(mw, "_print", Mock())

    def git(cmd, **kw):
        if cmd[0] in {"merge", "commit"}:
            return CompletedProcess(cmd, 1, "", "hook refused")
        return CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mw, "_run_git", git)
    monkeypatch.setattr(
        "yoke_core.engines.merge_worktree_rebase.auto_resolve_conflicts",
        lambda ctx: (2, []),
    )
    result = do_rebase_or_merge(ctx)
    assert result[0] == 1 and "hook refused" in result[1]
