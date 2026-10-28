"""Real Git histories preserve prior merge resolutions at QA and landing."""

from __future__ import annotations

import subprocess
from unittest.mock import Mock

import pytest

from yoke_core.domain import lane_base_update
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.engines import merge_worktree
from yoke_core.engines.merge_worktree_context import MergeArgs, MergeContext
from yoke_core.engines.merge_worktree_rebase import do_rebase_or_merge


def git(repo, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=check
    )


def commit(repo, name, content):
    (repo / name).write_text(content)
    git(repo, "add", name)
    git(repo, "commit", "-qm", content)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def history(tmp_path, shape):
    remote = tmp_path / "remote"
    repo = tmp_path / "lane"
    git(tmp_path, "init", "--bare", str(remote))
    git(tmp_path, "init", "-b", "main", str(repo))
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "core.hooksPath", "/dev/null")
    commit(repo, "shared", "initial\n")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-qb", "lane")
    if shape != "linear":
        git(repo, "checkout", "-qb", "side")
        commit(repo, "shared", "side\n")
        git(repo, "checkout", "lane")
        commit(repo, "shared", "lane\n")
        assert git(repo, "merge", "side", check=False).returncode == 1
        commit(repo, "shared", "resolved\n")
    else:
        commit(repo, "lane-file", "lane\n")
    original = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "checkout", "main")
    if shape == "conflict":
        commit(repo, "shared", "new base\n")
    else:
        commit(repo, "base-file", "base\n")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "lane")
    return repo, original


@pytest.mark.parametrize("driver", ["qa", "landing"])
@pytest.mark.parametrize("shape", ["clean", "conflict", "linear"])
def test_base_update_preserves_resolutions(tmp_path, monkeypatch, driver, shape):
    repo, original = history(tmp_path, shape)
    calls = []

    def run(*args):
        calls.append(args)
        return git(repo, *args, check=False)

    if driver == "qa":
        monkeypatch.setattr(lane_base_update, "git", lambda checkout, *a, **kw: run(*a))
        monkeypatch.setattr(
            "yoke_core.engines.merge_worktree_prepare_state._stash_classify_gate",
            lambda ctx: None,
        )

        def update():
            try:
                lane_base_update.bring_lane_current(
                    repo, branch="lane", target="main", project="widgets"
                )
            except lane_base_update.LaneBaseUpdateRefused as exc:
                raise QaCaseExecutionError(str(exc)) from exc
    else:
        monkeypatch.setattr(merge_worktree, "_run_git", lambda args, **kw: run(*args))
        monkeypatch.setattr(merge_worktree, "_print", Mock())
        monkeypatch.setattr(
            "yoke_core.domain.project_settings.get_project_int", lambda *a: 2
        )
        monkeypatch.setattr(
            "yoke_core.engines.merge_worktree_rebase.auto_resolve_conflicts",
            Mock(
                side_effect=AssertionError(
                    "must not replay or auto-resolve merge conflicts"
                )
            ),
        )
        ctx = MergeContext(
            args=MergeArgs(branch="lane", target="main"),
            repo_root=str(repo),
            worktree_path=str(repo),
            project="widgets",
        )

        def update():
            result = do_rebase_or_merge(ctx)
            if result:
                raise QaCaseExecutionError(result[1])

    if shape == "conflict":
        with pytest.raises(QaCaseExecutionError, match="lane_merge_conflict") as raised:
            update()
        assert "shared" in str(raised.value)
        assert "merge-shaped" in str(raised.value)
        assert "resolve" in str(raised.value)
        assert git(repo, "rev-parse", "HEAD").stdout.strip() == original
        assert not (repo / ".git" / "MERGE_HEAD").exists()
        assert git(repo, "status", "--porcelain").stdout == ""
    else:
        update()
        assert (
            git(repo, "merge-base", "--is-ancestor", "origin/main", "HEAD").returncode
            == 0
        )
        if shape == "clean":
            assert (
                git(repo, "merge-base", "--is-ancestor", original, "HEAD").returncode
                == 0
            )
            assert (repo / "shared").read_text() == "resolved\n"
        else:
            assert git(repo, "rev-list", "--merges", "origin/main..HEAD").stdout == ""
    assert any(c[0] == "rebase" for c in calls) == (shape == "linear")
    if shape != "linear":
        assert any(c[0] == "merge" and "--no-edit" in c for c in calls)
