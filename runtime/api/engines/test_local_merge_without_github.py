"""Both merge routes land without GitHub or a remote-tracking default ref."""

from __future__ import annotations

import subprocess

import pytest

from runtime.api.domain.standalone_merge_simulation_support import git
from runtime.api.engines.local_merge_test_support import (
    make_local_checkout,
    assert_landed_clean,
)
from yoke_core.domain import standalone_item_merge as boundary
from yoke_core.engines import merge_worktree as engine
from yoke_core.engines import merge_worktree_runner as runner
from yoke_core.domain import merge_github_authority as authority


@pytest.mark.parametrize("layout", ["tracking-ref", "unfetched-remote", "no-remote"])
@pytest.mark.parametrize("standalone", [False, True])
def test_disconnected_merge_lands_both_sides_without_publication(
    monkeypatch,
    tmp_path,
    layout,
    standalone,
):
    repo, lane, ctx = make_local_checkout(monkeypatch, tmp_path, layout)
    source = git(lane, "rev-parse", "HEAD")
    monkeypatch.setattr(
        runner,
        "validate_github_auth_for_merge",
        lambda *_a: pytest.fail("No App admission for a skipped project"),
    )
    commands = []
    real_git = engine._run_git

    def tracked_git(args, **kwargs):
        commands.append(args)
        return real_git(args, **kwargs)

    monkeypatch.setattr(engine, "_run_git", tracked_git)
    if standalone:
        outcome = boundary.merge_standalone_branch(
            item_id=7,
            branch="finished",
            commit_sha=source,
            target="main",
            repo_root=str(repo),
            project="local-project",
            local_merge=True,
        )
        assert outcome.ok, outcome.error
        assert not outcome.pushed
        assert outcome.touched_files == ("feature.txt",)
        assert "local" in outcome.output.lower()
        if layout != "no-remote":
            assert "not pushed because GitHub is not connected" in outcome.output
    else:
        assert runner.run(ctx.args) == 0
        source = git(lane, "rev-parse", "HEAD")
    assert_landed_clean(repo, lane, source)
    if layout == "no-remote":
        assert not any(args[0] == "fetch" for args in commands)


def test_failed_trial_without_merge_state_restores_clean_branch(
    monkeypatch, tmp_path, capsys
):
    _, lane, ctx = make_local_checkout(monkeypatch, tmp_path, "no-remote")
    ctx.args.target = "missing-default"
    source = git(lane, "rev-parse", "HEAD")
    commands = []
    real_git = engine._run_git

    def tracked_git(args, **kwargs):
        commands.append(args)
        return real_git(args, **kwargs)

    monkeypatch.setattr(engine, "_run_git", tracked_git)
    assert engine.trial_merge(ctx) == (1, [])
    assert git(lane, "rev-parse", "HEAD") == source
    assert git(lane, "branch", "--show-current") == "finished"
    assert git(lane, "status", "--porcelain") == ""
    assert ["merge", "--abort"] not in commands
    assert "Merge abort also failed" not in capsys.readouterr().err


def test_connected_direct_merge_still_requires_app_admission(monkeypatch, tmp_path):
    _, _, ctx = make_local_checkout(monkeypatch, tmp_path, "tracking-ref")
    ctx.args.standalone = True
    monkeypatch.setattr(authority, "github_merge_enabled", lambda _p: True)
    monkeypatch.setattr(
        runner,
        "validate_github_auth_for_merge",
        lambda *_a: (False, "missing connected App authorization"),
    )
    assert runner.run(ctx.args) == 1


def test_unreadable_project_mode_refuses_before_landing(monkeypatch, tmp_path, capsys):
    repo, lane, ctx = make_local_checkout(monkeypatch, tmp_path, "tracking-ref")
    ctx.args.standalone = True
    source = git(lane, "rev-parse", "HEAD")

    def unreadable(_project):
        raise RuntimeError("binding read unavailable")

    monkeypatch.setattr(authority, "github_merge_enabled", unreadable)
    assert runner.run(ctx.args) == 1
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", source, "main"],
            capture_output=True,
        ).returncode
        == 1
    )
    assert "github_merge_mode_unreadable" in capsys.readouterr().err
