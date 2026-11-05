"""Copied merge repositories relocate pointers and isolate Git mutations."""

from types import SimpleNamespace
from pathlib import Path

import pytest

from runtime.api import merge_worktree_test_repository as repositories
from runtime.api.test_merge_worktree_full import TEST_BRANCH, _git


def test_module_template_is_built_once_and_copies_are_independent(
    tmp_path, tmp_path_factory, monkeypatch
):
    module = SimpleNamespace(stash=pytest.Stash())
    request = SimpleNamespace(
        node=SimpleNamespace(getparent=lambda _: module),
        getfixturevalue=lambda _: tmp_path_factory,
    )
    builds = []
    build = repositories._build_repository

    def record_build(root, branch):
        builds.append(root)
        build(root, branch)

    monkeypatch.setattr(repositories, "_build_repository", record_build)
    copies = [tmp_path / name for name in ("first", "second")]
    for root in copies:
        repositories.copy_repository(root, request, TEST_BRANCH)
        for part in ("repo", "origin.git"):
            assert (
                _git(root / part, "config", "maintenance.auto").stdout.strip()
                == "false"
            )
            assert _git(root / part, "config", "gc.auto").stdout.strip() == "0"
        assert _git(root / "repo", "remote", "get-url", "origin").stdout.strip() == str(
            root / "origin.git"
        )
        assert (
            Path(
                _git(root / "worktree", "rev-parse", "--git-common-dir").stdout.strip()
            ).resolve()
            == (root / "repo" / ".git").resolve()
        )
        assert _git(root / "worktree", "status", "--porcelain").stdout == ""
    assert len(builds) == 1
    (copies[0] / "worktree" / "feature.txt").write_text("changed\n")
    _git(copies[0] / "worktree", "add", "feature.txt")
    _git(copies[0] / "worktree", "commit", "-m", "only first copy")
    _git(copies[0] / "worktree", "push", "origin", TEST_BRANCH)
    assert (copies[1] / "worktree" / "feature.txt").read_text() == "feature work\n"
    assert (
        _git(copies[0] / "origin.git", "rev-parse", TEST_BRANCH).stdout
        != _git(copies[1] / "origin.git", "rev-parse", TEST_BRANCH).stdout
    )
