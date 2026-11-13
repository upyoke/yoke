"""The sweep's registry hygiene: one prune, driver trees left to their pass.

Every sweep runs ``git worktree prune`` once, so a registration whose folder
is gone is dropped wherever it lived, while locked registrations survive.
Deploy-run driver trees are judged only by the deploy-run pass, so the item
pass never reports them as having no terminal owner. Unregistered managed
folders holding only ignored files are removed; one holding a non-ignored
file is kept and named.
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
from yoke_core.engines import deploy_run_worktree_retirement as _retirement
from yoke_core.engines.deploy_run_worktree_naming import driver_worktree_path
from yoke_core.engines.merge_worktree_safe_prune import prune_managed_worktrees


def _listed(repo: Path) -> str:
    return _git(repo, "worktree", "list", "--porcelain").stdout


def test_a_registration_whose_folder_is_gone_anywhere_is_pruned(
    monkeypatch, tmp_path: Path
):
    repo, _worktree, branch = _repo(tmp_path)
    adhoc = tmp_path / "scratch" / "adhoc"
    _git(repo, "worktree", "add", "--detach", str(adhoc), "HEAD")
    shutil.rmtree(adhoc)
    git_io, _lines = _install(monkeypatch, repo, _Conn(branch))

    prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert str(adhoc) not in _listed(repo)


def test_a_locked_registration_survives_the_prune(monkeypatch, tmp_path: Path):
    repo, _worktree, branch = _repo(tmp_path)
    held = tmp_path / "scratch" / "held"
    _git(repo, "worktree", "add", "--detach", str(held), "HEAD")
    _git(repo, "worktree", "lock", "--reason", "initializing", str(held))
    shutil.rmtree(held)
    git_io, _lines = _install(monkeypatch, repo, _Conn(branch))

    prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert str(held) in _listed(repo)


def test_a_deploy_run_tree_gets_no_item_pass_line(monkeypatch, tmp_path: Path):
    repo, _worktree, branch = _repo(tmp_path)
    driver = driver_worktree_path(repo, "run-20260101-009")
    _git(repo, "worktree", "add", "--detach", str(driver), "HEAD")
    monkeypatch.setattr(_retirement, "_run_status", lambda _run_id: ("executing", ""))
    git_io, lines = _install(monkeypatch, repo, _Conn(branch))

    sweep = prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    driver_lines = [line for line in lines if str(driver.resolve()) in line]
    assert driver_lines
    assert not any("no single terminal owner" in line for line in driver_lines)
    driver_kept = [
        lane for lane in sweep.preserved if lane.path == str(driver.resolve())
    ]
    assert len(driver_kept) == 1 and "executing" in driver_kept[0].reason


def test_an_unregistered_folder_of_only_ignored_files_is_removed(
    monkeypatch, tmp_path: Path
):
    repo, _worktree, branch = _repo(tmp_path)
    stray = repo / ".worktrees" / "PLAT-1"
    (stray / "webapp" / ".next" / "cache").mkdir(parents=True)
    (stray / "webapp" / ".next" / "cache" / "data").write_text("x", encoding="utf-8")
    (stray / "__pycache__").mkdir()
    git_io, lines = _install(monkeypatch, repo, _Conn(branch))

    sweep = prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert not stray.exists()
    assert str(stray.resolve()) in sweep.removed
    assert any("only ignored files" in line for line in lines)


def test_an_unregistered_folder_with_a_non_ignored_file_is_kept(
    monkeypatch, tmp_path: Path
):
    repo, _worktree, branch = _repo(tmp_path)
    stray = repo / ".worktrees" / "PLAT-2"
    (stray / ".next").mkdir(parents=True)
    (stray / "notes").mkdir()
    (stray / "notes" / "draft.md").write_text("keep\n", encoding="utf-8")
    git_io, _lines = _install(monkeypatch, repo, _Conn(branch))

    sweep = prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert (stray / "notes" / "draft.md").read_text(encoding="utf-8") == "keep\n"
    [kept] = [lane for lane in sweep.preserved if lane.path == str(stray.resolve())]
    assert kept.reason.endswith("notes/draft.md")
