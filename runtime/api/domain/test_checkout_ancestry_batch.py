"""Checkout containment answers the same verdicts without per-commit git."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import checkout_ancestry
from yoke_core.domain import deployment_run_carried_work_sources as sources
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


def _walk(
    repo: Path, lane: str, *, base: str, head: str, commits: tuple[str, ...]
) -> str:
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
    _git(
        repo,
        "-c",
        "commit.gpgsign=false",
        "merge",
        "-q",
        "--no-ff",
        "--no-edit",
        "lane",
    )
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
    raw_time = _git(repo, "show", "-s", "--format=%cI", feature)
    assert source.commit_time(feature) == parse_instant(raw_time)
    assert source._fact(feature)[0] == raw_time


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
    ancestor_calls = [
        args for args in recorded if args[:2] == ("merge-base", "--is-ancestor")
    ]
    parent_calls = [
        args for args in recorded if args[:1] == ("rev-list",) and "--parents" in args
    ]
    assert len(ancestor_calls) == 1
    assert len(parent_calls) == 1
    assert checkout_ancestry.commit_is_ancestor(
        checkout_ancestry.parent_graph(str(repo), head), head, lanes[3]
    )


def _colliding_commits(repo: Path) -> tuple[str, str]:
    """Write two commits whose shas share their first four hex digits."""
    tree = _git(repo, "hash-object", "-t", "tree", "-w", "/dev/null")
    seen: dict[str, bytes] = {}
    for index in range(100_000):
        body = (
            f"tree {tree}\nauthor a <a@x> 0 +0000\ncommitter a <a@x> 0 +0000\n\n"
            f"c{index}\n"
        ).encode()
        sha = hashlib.sha1(b"commit %d\0" % len(body) + body).hexdigest()
        if sha[:4] in seen:
            written = [
                subprocess.run(
                    ["git", "-C", str(repo), "hash-object", "-t", "commit", "-w"]
                    + ["--stdin"],
                    input=content,
                    check=True,
                    capture_output=True,
                )
                .stdout.decode()
                .strip()
                for content in (seen[sha[:4]], body)
            ]
            return written[0], written[1]
        seen[sha[:4]] = body
    raise AssertionError("no colliding prefix found")


def test_batched_resolution_answers_what_rev_parse_answers(tmp_path: Path) -> None:
    repo = _init(tmp_path / "repo")
    tip = _commit(repo, "tip")
    _git(repo, "branch", "lane")
    first, _second = _colliding_commits(repo)
    refs = ["lane", "main", tip, tip[:9], first[:4], first, "no-such-branch", ""]
    expected = {
        ref: git.git_out(str(repo), "rev-parse", "--verify", f"{ref}^{{commit}}")
        for ref in refs
    }
    assert expected[first[:4]] == "" and expected["lane"] == tip
    assert checkout_ancestry.resolve_commits(str(repo), refs) == expected
    assert LocalCheckoutSource(str(repo)).resolve_commits(refs) == expected
    assert checkout_ancestry.resolve_commits(str(tmp_path / "gone"), ["main"]) == {
        "main": ""
    }


def test_lane_resolution_git_does_not_scale_with_item_count(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _init(tmp_path / "repo")
    base = _commit(repo, "base")
    lanes = []
    for index in range(12):
        lanes.append(_commit(repo, f"c{index}"))
        _git(repo, "branch", f"lane-{index}")
    head = lanes[-1]
    real = subprocess.run
    calls: list[Any] = []

    def _count(argv, *args, **kwargs):
        if argv and argv[0] == "git":
            calls.append(argv)
        return real(argv, *args, **kwargs)

    def _git_calls(item_count: int) -> int:
        # Odd lanes record a sha the checkout lacks, so their branch answers.
        rows = [
            (index, "2026-10-16T00:00:00Z", None, None, f"lane-{index}")
            + ((lanes[index] if index % 2 == 0 else "f" * 40), False)
            for index in range(item_count)
        ]
        monkeypatch.setattr(sources, "_safe_rows", lambda *a, **k: rows)
        source = LocalCheckoutSource(str(repo))
        commits = source.commit_range(base, head).commits
        resolved: dict[str, set[int]] = {}
        calls.clear()
        sources._resolve_item_metadata(
            object(),
            project_id=1,
            source=source,
            base=base,
            head=head,
            commits=commits,
            known_items={index: f"YOK-{index}" for index in range(item_count)},
            resolved=resolved,
            warnings=[],
        )
        assert resolved == {lanes[i]: {i} for i in range(item_count)}
        return len(calls)

    monkeypatch.setattr(subprocess, "run", _count)
    assert _git_calls(4) == _git_calls(12)
