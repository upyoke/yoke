"""Safety proofs for automatic managed-worktree pruning.

The DB authority verdict now routes through the transport-aware
``merge.prune.authority_verdict`` relay. These end-to-end proofs drive the
REAL ``handle_prune_authority_verdict`` handler over a fake in-memory
connection (the same controlled-row conn the pre-relay tests used), so the
prune/keep decision for terminal, actively-claimed, dirty, unmerged, and
mixed-owner worktrees is proven unchanged while the engine relays the
verdict instead of opening a bare ``parent._connect()``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from runtime.api.engines._merge_prune_test_helpers import (
    _Conn,
    _git,
    _install,
    _repo,
)
from yoke_core.engines import merge_worktree_safe_prune as _safe_prune
from yoke_core.engines.merge_worktree_safe_prune import prune_managed_worktrees


def test_clean_terminal_merged_worktree_and_branch_are_pruned(
    monkeypatch, tmp_path: Path
):
    repo, worktree, branch = _repo(tmp_path)
    git_io, lines = _install(monkeypatch, repo, _Conn(branch))
    cleaned_trust: list[Path] = []
    monkeypatch.setattr(
        _safe_prune,
        "worktree_cleanup_warning",
        lambda path: cleaned_trust.append(Path(path)) or "",
    )

    sweep = prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert not worktree.exists()
    assert _git(repo, "branch", "--list", branch).stdout.strip() == ""
    assert any("Pruned terminal merged worktree" in line for line in lines)
    assert sweep.removed == (str(worktree.resolve()),)
    assert sweep.preserved == ()
    assert sweep.payload()["skipped"] == ""
    assert cleaned_trust == [worktree.resolve()]


def test_dirty_terminal_worktree_is_preserved(monkeypatch, tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    (worktree / "evidence.txt").write_text("keep me\n", encoding="utf-8")
    git_io, lines = _install(monkeypatch, repo, _Conn(branch))

    sweep = prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert branch in _git(repo, "branch", "--list", branch).stdout
    assert any("unignored changes present: evidence.txt" in line for line in lines)
    assert sweep.removed == ()
    assert sweep.payload()["preserved"] == [
        {
            "path": str(worktree.resolve()),
            "reason": "unignored changes present: evidence.txt",
        }
    ]


def test_locked_terminal_worktree_is_preserved_with_the_lock_named(
    monkeypatch, tmp_path: Path
):
    """A lock is an operator's hold; the sweep names it instead of forcing it."""
    repo, worktree, branch = _repo(tmp_path)
    _git(repo, "worktree", "lock", "--reason", "initializing", str(worktree))
    git_io, lines = _install(monkeypatch, repo, _Conn(branch))

    sweep = prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert branch in _git(repo, "branch", "--list", branch).stdout
    assert sweep.preserved[0].reason == "worktree is locked (initializing)"
    assert any("locked (initializing)" in line for line in lines)


def test_known_python_and_node_caches_are_removed_before_prune(
    monkeypatch, tmp_path: Path
):
    repo, worktree, branch = _repo(tmp_path)
    cache_files = (
        worktree / "__pycache__" / "module.pyc",
        worktree / ".pytest_cache" / "state",
        worktree / ".ruff_cache" / "state",
        worktree / ".venv" / "pyvenv.cfg",
        worktree / "packages" / "core" / "build" / "wheel",
        worktree / "packages" / "core" / "src" / "core.egg-info" / "PKG-INFO",
        worktree / "webapp" / "node_modules" / "pkg" / "index.js",
        worktree / "webapp" / ".next" / "cache" / "data",
        worktree / "webapp" / ".vite" / "cache" / "data",
    )
    for path in cache_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated\n", encoding="utf-8")
    git_io, _lines = _install(monkeypatch, repo, _Conn(branch))

    prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert not worktree.exists()
    assert _git(repo, "branch", "--list", branch).stdout.strip() == ""


def test_unknown_ignored_content_is_preserved(monkeypatch, tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    protected = worktree / ".private" / "operator-note"
    protected.parent.mkdir(parents=True)
    protected.write_text("keep me\n", encoding="utf-8")
    git_io, lines = _install(monkeypatch, repo, _Conn(branch))

    prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert protected.read_text(encoding="utf-8") == "keep me\n"
    assert worktree.exists()
    assert any("unknown ignored files present: .private/" in line for line in lines)


def test_active_claim_preserves_terminal_worktree(monkeypatch, tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    git_io, lines = _install(monkeypatch, repo, _Conn(branch, claimed=True))

    prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert any("actively claimed" in line for line in lines)


def test_active_item_owned_path_claim_preserves_terminal_worktree(
    monkeypatch, tmp_path: Path
):
    repo, worktree, branch = _repo(tmp_path)
    git_io, lines = _install(monkeypatch, repo, _Conn(branch, path_claimed=True))

    prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert branch in _git(repo, "branch", "--list", branch).stdout
    assert any("actively claimed" in line for line in lines)


def test_unmerged_terminal_worktree_is_preserved(monkeypatch, tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    (worktree / "feature.txt").write_text("new\n", encoding="utf-8")
    _git(worktree, "add", "feature.txt")
    _git(worktree, "commit", "-m", "unmerged")
    git_io, lines = _install(monkeypatch, repo, _Conn(branch))

    prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert any(
        f"worktree branch {branch} is not merged into origin/main" in line
        for line in lines
    )


def test_nonterminal_owner_preserves_merged_worktree(monkeypatch, tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    git_io, _lines = _install(monkeypatch, repo, _Conn(branch, terminal=False))

    prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert branch in _git(repo, "branch", "--list", branch).stdout


def test_terminal_and_nonterminal_owners_sharing_branch_are_preserved(
    monkeypatch,
    tmp_path: Path,
):
    repo, worktree, branch = _repo(tmp_path)
    git_io, _lines = _install(monkeypatch, repo, _Conn(branch, mixed_owner=True))

    prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert branch in _git(repo, "branch", "--list", branch).stdout


def test_unavailable_db_authority_skips_all_pruning(monkeypatch, tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    git_io, lines = _install(monkeypatch, repo, _Conn(branch, unavailable=True))

    sweep = prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    # Fail closed: the terminal merged worktree is preserved and the skip
    # narrative fires, exactly as the pre-relay bare-connect failure did.
    assert worktree.exists()
    assert branch in _git(repo, "branch", "--list", branch).stdout
    assert any("DB authority unavailable" in line for line in lines)
    assert sweep.payload()["skipped"] == "DB authority unavailable"


def test_an_absent_lane_directory_counts_as_swept(monkeypatch, tmp_path: Path):
    """A lane that is already gone is the state the sweep aims at.

    Git still registers a worktree whose directory was removed by hand, and
    reading that registration as a refusal ended the whole sweep on its
    first stale entry — every reclaimable lane behind it stayed on disk, and
    every later landing reported the same ENOENT under the closing item's
    own name.
    """
    repo, worktree, branch = _repo(tmp_path)
    shutil.rmtree(worktree)
    git_io, lines = _install(monkeypatch, repo, _Conn(branch))

    sweep = prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert sweep.skipped == ""
    assert sweep.preserved == ()
    assert sweep.removed == (str(worktree.resolve()),)
    assert any("absent worktree" in line for line in lines)
    # The registration went with it, so the branch rejoins the branch pass
    # and is retired there on its own landing proof.
    assert _git(repo, "branch", "--list", branch).stdout.strip() == ""


def test_an_absent_lane_does_not_stop_the_lanes_behind_it(
    monkeypatch, tmp_path: Path
):
    repo, worktree, branch = _repo(tmp_path)
    second = repo / ".worktrees" / "second"
    _git(repo, "worktree", "add", "-b", "second-lane", str(second), "main")
    shutil.rmtree(worktree)
    git_io, _lines = _install(monkeypatch, repo, _Conn("second-lane"))

    sweep = prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    # The absent registration is examined and passed over — its item is not
    # terminal, so it was never this sweep's to reclaim — and the lane
    # behind it is still examined and reclaimed on its own proofs.
    assert sweep.skipped == ""
    assert sweep.removed == (str(second.resolve()),)
    assert not second.exists()
    assert worktree.exists() is False
