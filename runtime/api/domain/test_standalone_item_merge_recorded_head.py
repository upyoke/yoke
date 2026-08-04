"""Recorded-identity regressions at the standalone merge boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import standalone_item_merge as merge_boundary
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext
from yoke_core.engines.merge_worktree_recorded_source import bind_recorded_source


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "base.txt").write_text("base\n")
    _git(root, "add", "base.txt")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "lane")
    (root / "feature.txt").write_text("recorded work\n")
    _git(root, "add", "feature.txt")
    _git(root, "commit", "-q", "-m", "feature")
    return root


def test_stale_same_named_ref_merges_the_recorded_head(
    repo: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = _git(repo, "rev-parse", "lane")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "branch", "-f", "lane", "main")
    monkeypatch.setattr(merge_boundary.receipts, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(merge_boundary.receipts, "record", lambda *_a, **_k: None)
    monkeypatch.setattr(merge_boundary, "stamp_merged_at", lambda *_a: None)
    monkeypatch.setattr(merge_boundary.git, "publish", lambda *_a: (False, ""))

    def merge_recorded(**kwargs):
        assert kwargs["source_sha"] == recorded
        _git(repo, "checkout", "-q", "main")
        _git(repo, "merge", "-q", "--no-edit", kwargs["source_sha"])
        return 0, ""

    monkeypatch.setattr(merge_boundary, "_run_merge_engine", merge_recorded)

    outcome = merge_boundary.merge_standalone_branch(
        item_id=7,
        branch="lane",
        commit_sha=recorded,
        target="main",
        repo_root=str(repo),
        project="yoke",
    )

    assert outcome.ok is True
    assert outcome.already_merged is False
    assert _git(repo, "show", "main:feature.txt") == "recorded work"


def test_terminal_transition_refuses_an_unreachable_recorded_head(
    repo: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    unreachable = _git(repo, "rev-parse", "lane")
    _git(repo, "checkout", "-q", "main")
    monkeypatch.setattr(
        merge_cli,
        "call_dispatcher",
        lambda **_k: pytest.fail("lifecycle dispatcher must not be called"),
    )

    error = merge_cli._transition_to_done(
        7, "reviewing-implementation", repo, "main", unreachable,
    )

    assert "not reachable" in error


def test_engine_rebinds_a_stale_lane_ref_to_recorded_head(repo: Path) -> None:
    recorded = _git(repo, "rev-parse", "lane")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "branch", "-f", "lane", "main")
    stale = _git(repo, "rev-parse", "lane")
    context = MergeContext(
        args=MergeArgs(branch="lane", source_sha=recorded),
        repo_root=str(repo),
    )

    assert bind_recorded_source(context, stale) == ""
    assert _git(repo, "rev-parse", "lane") == recorded
