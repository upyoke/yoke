"""Module-owned Git repository templates for merge subprocess tests."""

import os
from pathlib import Path
import shutil
import subprocess
import warnings

import pytest

_REPOSITORY_TEMPLATE = pytest.StashKey[Path]()


def _build_repository(root: Path, branch: str) -> None:
    from runtime.api.merge_worktree_full_test_support import _git, _write_file

    origin, repo, worktree = (
        root / part for part in ("origin.git", "repo", "worktree")
    )
    for path, bare in ((origin, True), (repo, False)):
        args = ["git", "init", "--initial-branch=main"]
        if bare:
            args.append("--bare")
        subprocess.run([*args, str(path)], capture_output=True, check=True)
        # Copies must observe an immutable template, with no detached Git
        # maintenance changing object files or removing lock files mid-copy.
        _git(path, "config", "maintenance.auto", "false")
        _git(path, "config", "gc.auto", "0")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")
    _write_file(repo / ".gitignore", ".yoke/BOARD.md\n.yoke/BOARD.md.ts\n")
    _write_file(repo / "README.md", "initial\n")
    _write_file(repo / ".yoke" / "BOARD.md", "# Board\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial commit")
    _git(repo, "push", "origin", "main")
    _git(repo, "branch", branch)
    _git(repo, "worktree", "add", str(worktree), branch)
    _write_file(worktree / "feature.txt", "feature work\n")
    _git(worktree, "add", "feature.txt")
    _git(worktree, "commit", "-m", "feature work")
    _git(worktree, "push", "origin", branch)


def copy_repository(tmp_path: Path, request, branch: str) -> None:
    """Build once for this test module, then relocate an independent copy."""
    module = request.node.getparent(pytest.Module)
    template = module.stash.get(_REPOSITORY_TEMPLATE, None)
    if template is None:
        factory = request.getfixturevalue("tmp_path_factory")
        template = factory.mktemp("merge-repository")
        _build_repository(template, branch)
        module.stash[_REPOSITORY_TEMPLATE] = template
    for part in ("origin.git", "repo", "worktree"):
        shutil.copytree(template / part, tmp_path / part, symlinks=True)
    # Git's linked-worktree pointers and origin URL are absolute. Rewrite
    # only those three text files; object storage and relative commondir stay.
    for relative in (
        "repo/.git/config",
        "repo/.git/worktrees/worktree/gitdir",
        "worktree/.git",
    ):
        _rewrite_in_place(tmp_path / relative, str(template), str(tmp_path))


def _rewrite_in_place(path: Path, old: str, new: str) -> None:
    """Replace text inside an existing file without recreating it.

    Git for Windows marks a linked worktree's ``.git`` file Hidden, and
    Windows denies a truncating create on a hidden file; opening the existing
    file for update keeps its attributes and is allowed.
    """
    attributes = getattr(os.stat(path), "st_file_attributes", None)
    if attributes is not None:  # YOK-5357 cause probe; removed once confirmed.
        warnings.warn(f"YOK-5357 attributes {path.name}: {attributes:#x}")
    with path.open("r+", encoding="utf-8", newline="") as handle:
        text = handle.read().replace(old, new)
        handle.seek(0)
        handle.write(text)
        handle.truncate()
