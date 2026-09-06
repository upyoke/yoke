"""Recorded-identity regressions at the standalone merge boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import standalone_item_merge as merge_boundary
from yoke_core.domain import standalone_item_merge_terminal as terminal
from yoke_core.domain.standalone_item_merge_landed import LandedLane
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
        terminal,
        "call_dispatcher",
        lambda **_k: pytest.fail("lifecycle dispatcher must not be called"),
    )

    error = terminal.transition_to_done(
        item_id=7,
        source_status="reviewing-implementation",
        repo_root=str(repo),
        lane=LandedLane(branch="lane", target="main", commit_sha=unreachable),
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


def test_ancestor_recorded_head_leaves_advanced_branch_untouched(repo: Path) -> None:
    """Reproduces the interrupted-merge/retry incident.

    The lane already contains the recorded commit and has moved past it --
    a prior interrupted run's own progress. Rewinding to the stale record
    would discard that progress and desync the checked-out worktree's
    index/files from the ref this rewinds behind them.
    """
    recorded = _git(repo, "rev-parse", "main")  # the older, now-stale record
    advanced = _git(repo, "rev-parse", "lane")  # lane already contains it
    context = MergeContext(
        args=MergeArgs(branch="lane", source_sha=recorded),
        repo_root=str(repo),
    )

    assert bind_recorded_source(context, advanced) == ""
    assert _git(repo, "rev-parse", "lane") == advanced


def test_divergent_recorded_head_refuses_without_rewinding(repo: Path) -> None:
    """Neither side is an ancestor of the other -- refuse, don't guess."""
    recorded = _git(repo, "rev-parse", "lane")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "other")
    (repo / "other.txt").write_text("unrelated\n")
    _git(repo, "add", "other.txt")
    _git(repo, "commit", "-q", "-m", "other")
    _git(repo, "branch", "-f", "lane", "other")
    diverged = _git(repo, "rev-parse", "lane")
    context = MergeContext(
        args=MergeArgs(branch="lane", source_sha=recorded),
        repo_root=str(repo),
    )

    error = bind_recorded_source(context, diverged)

    assert "diverged" in error
    assert _git(repo, "rev-parse", "lane") == diverged


def test_record_lane_head_after_merge_persists_worktree_head(
    repo: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runs right after the engine's own rebase/merge: head-only, best-effort."""
    from yoke_core.engines.merge_worktree_recorded_source import (
        record_lane_head_after_merge,
    )
    import yoke_cli.commands.adapters.project_snapshot as project_snapshot

    calls: list[dict] = []
    monkeypatch.setattr(
        project_snapshot,
        "sync_local_snapshot_for_write",
        lambda **kwargs: calls.append(kwargs) or {"status": "ok"},
    )
    context = MergeContext(
        args=MergeArgs(branch="lane"),
        repo_root=str(repo),
        worktree_path=str(repo),
        project="yoke",
    )

    record_lane_head_after_merge(context)

    assert calls == [{
        "project": "yoke",
        "repo_root": str(repo),
        "integration_target": None,
        "session_id": None,
        "head_only": True,
    }]


def test_unrecorded_head_falls_back_to_the_branch(
    repo: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A control plane older than item_worktrees.commit_sha records nothing,
    # and the deploy that would teach it to is itself work that has to merge.
    # Refusing here makes the client's own upgrade unreachable.
    head = _git(repo, "rev-parse", "lane")
    _git(repo, "checkout", "-q", "main")
    monkeypatch.setattr(merge_boundary.receipts, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(merge_boundary.receipts, "record", lambda *_a, **_k: None)
    monkeypatch.setattr(merge_boundary, "stamp_merged_at", lambda *_a: None)
    monkeypatch.setattr(merge_boundary.git, "publish", lambda *_a: (False, ""))

    def merge_derived(**kwargs):
        assert kwargs["source_sha"] == head
        _git(repo, "checkout", "-q", "main")
        _git(repo, "merge", "-q", "--no-edit", kwargs["source_sha"])
        return 0, ""

    monkeypatch.setattr(merge_boundary, "_run_merge_engine", merge_derived)

    outcome = merge_boundary.merge_standalone_branch(
        item_id=7,
        branch="lane",
        commit_sha="",
        target="main",
        repo_root=str(repo),
        project="yoke",
    )

    assert outcome.ok is True
    assert _git(repo, "show", "main:feature.txt") == "recorded work"


def test_unrecorded_head_says_the_value_was_derived(
    repo: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silently substituting a weaker guarantee would be the worse failure."""
    monkeypatch.setattr(merge_boundary.receipts, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(merge_boundary.receipts, "record", lambda *_a, **_k: None)
    monkeypatch.setattr(merge_boundary, "stamp_merged_at", lambda *_a: None)
    monkeypatch.setattr(merge_boundary.git, "publish", lambda *_a: (False, ""))
    monkeypatch.setattr(merge_boundary, "_run_merge_engine", lambda **_k: (0, ""))

    outcome = merge_boundary.merge_standalone_branch(
        item_id=7,
        branch="lane",
        commit_sha="",
        target="main",
        repo_root=str(repo),
        project="yoke",
    )

    assert any("not recorded by the control plane" in w for w in outcome.warnings)


def test_an_unresolvable_branch_still_refuses(
    repo: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fallback derives a real commit or it fails; it never invents one.
    monkeypatch.setattr(merge_boundary.git, "branch_exists", lambda *_a: True)
    monkeypatch.setattr(merge_boundary.receipts, "load", lambda *_a, **_k: None)

    outcome = merge_boundary.merge_standalone_branch(
        item_id=7,
        branch="no-such-lane",
        commit_sha="",
        target="main",
        repo_root=str(repo),
        project="yoke",
    )

    assert outcome.ok is False
    assert "could not be resolved" in outcome.error
