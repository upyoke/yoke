"""Checkout containment answers the same verdicts without per-commit git."""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_core.domain import checkout_ancestry
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.deployment_run_carried_work_source import LocalCheckoutSource


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init(repo: Path) -> Path:
    repo.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(repo, "config", "user.name", "ancestry-test")
    _git(repo, "config", "user.email", "ancestry-test@example.invalid")
    return repo


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=ancestry-test",
        "-c",
        "user.email=ancestry-test@example.invalid",
        "commit",
        "-q",
        "-m",
        name,
        "--no-gpg-sign",
    )
    return _git(repo, "rev-parse", "HEAD")


def _walk(repo: Path, lane: str, *, base: str, head: str, commits: tuple[str, ...]) -> str:
    if git.is_ancestor(str(repo), lane, base):
        return ""
    if not git.is_ancestor(str(repo), lane, head):
        return ""
    for commit in commits:
        if git.is_ancestor(str(repo), lane, commit):
            return commit
    return ""


def test_carrying_commit_matches_per_commit_is_ancestor(tmp_path: Path) -> None:
    repo = _init(tmp_path / "repo")
    base = _commit(repo, "base")
    side = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "lane")
    feature = _commit(repo, "feature")
    _git(repo, "checkout", "-q", "main")
    mid = _commit(repo, "mid")
    _git(repo, "-c", "commit.gpgsign=false", "merge", "-q", "--no-ff", "--no-edit", "lane")
    merge = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, "tip")
    source = LocalCheckoutSource(str(repo))
    commits = source.commit_range(base, head).commits
    for lane in (base, side, feature, mid, merge, head, "0" * 40):
        assert source.carrying_commit(
            lane, base=base, head=head, commits=commits
        ) == _walk(repo, lane, base=base, head=head, commits=commits)
    assert source.contains_commit(head, feature) is True
    assert source.contains_commit(base, feature) is False
    assert source.commit_message(feature) == "feature"


def test_containment_git_does_not_scale_with_candidate_count(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _init(tmp_path / "repo")
    base = _commit(repo, "base")
    lanes = [base]
    for index in range(8):
        lanes.append(_commit(repo, f"c{index}"))
    head = lanes[-1]
    recorded: list[tuple[str, ...]] = []
    real = git._git

    def _count(repo_root: str, *args: str):
        recorded.append(args)
        return real(repo_root, *args)

    monkeypatch.setattr(git, "_git", _count)
    source = LocalCheckoutSource(str(repo))
    commits = source.commit_range(base, head).commits
    for lane in lanes:
        source.carrying_commit(lane, base=base, head=head, commits=commits)
        source.contains_commit(head, lane)
    ancestor_calls = [args for args in recorded if args[:2] == ("merge-base", "--is-ancestor")]
    parent_calls = [
        args for args in recorded if args[:1] == ("rev-list",) and "--parents" in args
    ]
    assert len(ancestor_calls) == 1
    assert len(parent_calls) == 1
    assert checkout_ancestry.commit_is_ancestor(
        checkout_ancestry.parent_graph(str(repo), head), head, lanes[3]
    )
