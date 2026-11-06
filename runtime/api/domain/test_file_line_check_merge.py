"""Staged line gates distinguish inherited merge growth from new growth."""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

from yoke_core.domain import file_line_check as core
from yoke_harness.git_hooks import file_line_check as harness

from runtime.api.domain.file_line_check_test_support import (
    _commit_file,
    _init_git_repo,
    _make_lines,
)


def git(repo: pathlib.Path, *args: str, check: bool = True):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=check,
        capture_output=True, text=True,
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
        (repo / "big.py").write_text(_make_lines(401 + extra_growth))
        git(repo, "add", "big.py")
    verdict = checker.changed_files_check(repo_root=repo, staged=True)
    changes = verdict.hard_fails if extra_growth else verdict.warnings
    change = next(c for c in changes if c.path == "big.py")
    assert verdict.ok is (not extra_growth)
    assert change.old_line_count == 401
    assert change.new_line_count == 401 + extra_growth


@pytest.mark.parametrize("checker", [core, harness])
def test_non_merge_still_refuses_growth(repo, checker):
    (repo / "big.py").write_text(_make_lines(401))
    git(repo, "add", "big.py")
    verdict = checker.changed_files_check(repo_root=repo, staged=True)
    assert not verdict.ok
    assert verdict.hard_fails[0].old_line_count == 400


@pytest.mark.parametrize("checker", [core, harness])
def test_head_can_be_larger_than_merge_parent(repo, checker):
    _commit_file(repo, "big.py", _make_lines(402))
    git(repo, "merge", "--no-commit", "--no-ff", "main", check=False)
    (repo / "big.py").write_text(_make_lines(402))
    git(repo, "add", "big.py")
    assert checker.changed_files_check(repo_root=repo, staged=True).ok


@pytest.mark.parametrize("checker", [core, harness])
def test_octopus_merge_reads_all_parents(repo, checker):
    git(repo, "checkout", "-b", "other")
    _commit_file(repo, "other.txt", "other\n")
    git(repo, "checkout", "lane")
    git(repo, "merge", "--no-commit", "--no-ff", "other", "main")
    merge_head = pathlib.Path(git(repo, "rev-parse", "--git-path", "MERGE_HEAD").stdout.strip())
    assert len((repo / merge_head).read_text().splitlines()) == 2
    verdict = checker.changed_files_check(repo_root=repo, staged=True)
    assert verdict.ok
    assert next(c for c in verdict.warnings if c.path == "big.py").old_line_count == 401


def install_line_hook(repo, name):
    hook = repo / ".git" / "hooks" / name
    hook.write_text(
        f"#!{sys.executable}\nimport sys\nsys.path[:] = {sys.path!r}\n"
        "from yoke_harness.git_hooks.pre_commit import main\n"
        "raise SystemExit(main())\n"
    )
    hook.chmod(0o755)


@pytest.mark.parametrize("extra_growth", [0, 1])
def test_pre_merge_commit_hook_checks_inherited_and_combined_growth(repo, extra_growth):
    if extra_growth:
        _commit_file(repo, "big.py", "lane\n" + _make_lines(400))
    install_line_hook(repo, "pre-merge-commit")
    result = git(repo, "merge", "--no-ff", "main", "-m", "Integrate base", check=False)
    assert result.returncode == extra_growth, result.stderr
    if extra_growth:
        assert "existing 401-line file grew" in result.stderr
    else:
        assert len(git(repo, "rev-list", "--parents", "-n", "1", "HEAD").stdout.split()) == 3


def test_automatic_octopus_merge_hook_reads_all_parents(repo):
    git(repo, "checkout", "-b", "other")
    _commit_file(repo, "other.txt", "other\n")
    git(repo, "checkout", "lane")
    install_line_hook(repo, "pre-merge-commit")
    result = git(repo, "merge", "--no-ff", "other", "main", "-m", "Integrate parents", check=False)
    assert result.returncode == 0, result.stderr
    assert len(git(repo, "rev-list", "--parents", "-n", "1", "HEAD").stdout.split()) == 4


@pytest.mark.parametrize("extra_growth", [0, 1])
def test_plain_commit_finishes_conflicted_merge(repo, extra_growth):
    # Change the same existing line on both sides to require resolution.
    git(repo, "checkout", "main")
    _commit_file(repo, "big.py", _make_lines(401).replace("x0\n", "base\n", 1))
    git(repo, "checkout", "lane")
    _commit_file(repo, "big.py", _make_lines(400).replace("x0\n", "lane\n", 1))
    result = git(repo, "merge", "--no-ff", "main", check=False)
    assert result.returncode == 1
    assert "CONFLICT" in result.stdout
    (repo / "big.py").write_text(_make_lines(401 + extra_growth))
    git(repo, "add", "big.py")
    install_line_hook(repo, "pre-commit")
    result = git(repo, "commit", "-m", "Resolve merge", check=False)
    assert result.returncode == extra_growth
    if extra_growth:
        assert "file-line-limit gate blocked" in result.stderr
        assert "existing 401-line file grew" in result.stderr
    else:
        assert len(git(repo, "rev-list", "--parents", "-n", "1", "HEAD").stdout.split()) == 3


@pytest.mark.parametrize("checker", [core, harness])
def test_merge_parent_lookup_in_linked_worktree(repo, tmp_path, checker):
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-b", "linked-lane", str(linked), "lane")
    git(linked, "merge", "--no-commit", "--no-ff", "main")
    assert (linked / ".git").is_file()
    assert checker.changed_files_check(repo_root=linked, staged=True).ok
