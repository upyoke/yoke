"""Staged line gates distinguish inherited merge growth from new growth."""

from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

from yoke_core.domain import file_line_check as core
from yoke_harness.git_hooks import file_line_check as harness

from runtime.api.domain.file_line_check_test_support import (
    _commit_file,
    _init_git_repo,
    _make_lines,
)


@pytest.mark.parametrize("width", [40, 64])
def test_merge_parent_environment_accepts_windows_uppercase_hashes(tmp_path, monkeypatch, width):
    from yoke_contracts.project_contract import file_line_git_scope as scope

    monkeypatch.setattr(scope, "_git", lambda *args: ".git/MERGE_HEAD")
    for key in tuple(os.environ):
        if key.startswith("GITHEAD_"):
            monkeypatch.delenv(key)
    oid = ("ABCDEF0123" * 7)[:width]
    monkeypatch.setenv(f"GITHEAD_{oid}", "incoming")

    assert scope.merge_parent_refs(tmp_path) == (oid.lower(),)


def git(repo: pathlib.Path, *args: str, check: bool = True):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=check,
        capture_output=True, text=True, encoding="utf-8",
    )


@pytest.fixture
def repo(tmp_path):
    _init_git_repo(tmp_path)
    _commit_file(tmp_path, ".yoke/project.config", "file_line_exception=big.py\n")
    _commit_file(tmp_path, "big.py", _make_lines(400))
    git(tmp_path, "checkout", "-b", "lane")
    _commit_file(tmp_path, "lane.txt", "lane\n")
    git(tmp_path, "checkout", "main")
    _commit_file(tmp_path, "big.py", _make_lines(401))
    git(tmp_path, "checkout", "lane")
    return tmp_path


@pytest.mark.parametrize("checker", [core, harness])
@pytest.mark.parametrize("extra_growth", [0, 1])
def test_merge_uses_largest_parent_count(repo, checker, extra_growth):
    git(repo, "merge", "--no-commit", "--no-ff", "main")
    if extra_growth:
        (repo / "big.py").write_text(_make_lines(401 + extra_growth), encoding="utf-8", newline="\n")
        git(repo, "add", "big.py")
    verdict = checker.changed_files_check(repo_root=repo, staged=True)
    changes = verdict.hard_fails if extra_growth else verdict.warnings
    change = next(c for c in changes if c.path == "big.py")
    assert verdict.ok is (not extra_growth)
    assert change.old_line_count == 401
    assert change.new_line_count == 401 + extra_growth


@pytest.mark.parametrize("checker", [core, harness])
def test_non_merge_still_refuses_growth(repo, checker):
    (repo / "big.py").write_text(_make_lines(401), encoding="utf-8", newline="\n")
    git(repo, "add", "big.py")
    verdict = checker.changed_files_check(repo_root=repo, staged=True)
    assert not verdict.ok
    assert verdict.hard_fails[0].old_line_count == 400


@pytest.mark.parametrize("checker", [core, harness])
def test_head_can_be_larger_than_merge_parent(repo, checker):
    _commit_file(repo, "big.py", _make_lines(402))
    git(repo, "merge", "--no-commit", "--no-ff", "main", check=False)
    (repo / "big.py").write_text(_make_lines(402), encoding="utf-8", newline="\n")
    git(repo, "add", "big.py")
    assert checker.changed_files_check(repo_root=repo, staged=True).ok


@pytest.mark.parametrize("checker", [core, harness])
def test_octopus_merge_reads_all_parents(repo, checker):
    git(repo, "checkout", "-b", "other")
    _commit_file(repo, "other.txt", "other\n")
    git(repo, "checkout", "lane")
    git(repo, "merge", "--no-commit", "--no-ff", "other", "main")
    merge_head = pathlib.Path(git(repo, "rev-parse", "--git-path", "MERGE_HEAD").stdout.strip())
    assert len((repo / merge_head).read_text(encoding="utf-8").splitlines()) == 2
    verdict = checker.changed_files_check(repo_root=repo, staged=True)
    assert verdict.ok
    assert next(c for c in verdict.warnings if c.path == "big.py").old_line_count == 401


@pytest.mark.parametrize("checker", [core, harness])
def test_merge_parent_lookup_in_linked_worktree(repo, tmp_path, checker):
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-b", "linked-lane", str(linked), "lane")
    git(linked, "merge", "--no-commit", "--no-ff", "main")
    assert (linked / ".git").is_file()
    assert checker.changed_files_check(repo_root=linked, staged=True).ok
