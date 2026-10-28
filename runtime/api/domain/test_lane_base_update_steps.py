"""Bringing a lane current with its base, one Git step at a time.

Real histories (merge-shaped, conflicting, linear) live in
``test_lane_base_update``; these pin the step order and each named refusal.
"""

from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from yoke_contracts.git_hook_markers import HEAD_RECORDING_SKIP_ENV
from yoke_core.domain import lane_base_update
from yoke_core.domain.lane_base_update import LaneBaseUpdateRefused


def _git_results(monkeypatch, results: dict[str, subprocess.CompletedProcess]):
    calls: list[tuple[str, ...]] = []

    def _fake_git(_checkout, *args, timeout=120):
        calls.append(args)
        return results.get(args[0], subprocess.CompletedProcess(list(args), 0, "", ""))

    monkeypatch.setattr(lane_base_update, "git", _fake_git)
    return calls


def _clean_worktree(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.engines.merge_worktree_prepare_state._stash_classify_gate",
        lambda _ctx: None,
    )


def test_a_lane_behind_the_base_is_fetched_then_rebased(monkeypatch):
    _clean_worktree(monkeypatch)
    calls = _git_results(
        monkeypatch,
        {"merge-base": subprocess.CompletedProcess([], 1, "", "")},
    )

    lane_base_update.bring_lane_current(
        "/tmp/tree",
        branch="PRJ-9",
        target="main",
        project="yoke",
    )

    assert calls[0] == ("fetch", "--quiet", "--no-tags", "origin", "main")
    assert calls[1] == (
        "merge-base",
        "--is-ancestor",
        "origin/main",
        "HEAD",
    )
    assert calls[2] == ("rev-list", "--merges", "origin/main..HEAD")
    assert calls[3] == ("rebase", "origin/main")


def test_lane_rebase_marks_replayed_commits_to_skip_snapshot_sync(monkeypatch):
    observed = {}

    def run(argv, **kwargs):
        observed.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(lane_base_update.process_group_reaping, "run_in_process_group", run)

    lane_base_update.git("/tmp/tree", "rebase", "origin/main", timeout=600)

    assert observed["env"][HEAD_RECORDING_SKIP_ENV] == "1"


def test_a_lane_containing_the_base_keeps_its_merge_topology(monkeypatch):
    _clean_worktree(monkeypatch)
    calls = _git_results(monkeypatch, {})

    lane_base_update.bring_lane_current(
        "/tmp/tree",
        branch="PRJ-9",
        target="main",
        project="yoke",
    )

    assert calls == [
        ("fetch", "--quiet", "--no-tags", "origin", "main"),
        ("merge-base", "--is-ancestor", "origin/main", "HEAD"),
    ]


def test_an_unreadable_ancestry_refuses_before_rebase(monkeypatch):
    _clean_worktree(monkeypatch)
    calls = _git_results(
        monkeypatch,
        {
            "merge-base": subprocess.CompletedProcess(
                [], 128, "", "could not read commit"
            )
        },
    )

    with pytest.raises(LaneBaseUpdateRefused, match="could not compare"):
        lane_base_update.bring_lane_current(
            "/tmp/tree",
            branch="PRJ-9",
            target="main",
            project="yoke",
        )

    assert ("rebase", "origin/main") not in calls


def test_uncommitted_work_stops_a_behind_lane_and_names_its_stash(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.engines.merge_worktree_prepare_state._stash_classify_gate",
        lambda _ctx: (4, "user-authored files at risk"),
    )
    calls = _git_results(
        monkeypatch,
        {"merge-base": subprocess.CompletedProcess([], 1, "", "")},
    )

    with pytest.raises(LaneBaseUpdateRefused, match="lane_uncommitted_work") as raised:
        lane_base_update.bring_lane_current(
            "/tmp/tree",
            branch="PRJ-9",
            target="main",
            project="yoke",
        )

    assert "yoke-pre-rebase-PRJ-9" in str(raised.value)
    assert [c[0] for c in calls] == ["fetch", "merge-base"]


def test_a_current_lane_never_reaches_the_stash_gate(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.engines.merge_worktree_prepare_state._stash_classify_gate",
        mock.Mock(side_effect=AssertionError("a current lane is not stashed")),
    )
    _git_results(monkeypatch, {})

    assert (
        lane_base_update.bring_lane_current(
            "/tmp/tree", branch="PRJ-9", target="main", project="yoke"
        )
        is False
    )


def test_a_conflicting_rebase_aborts_and_names_the_conflicted_paths(monkeypatch):
    _clean_worktree(monkeypatch)
    calls = _git_results(
        monkeypatch,
        {
            "merge-base": subprocess.CompletedProcess([], 1, "", ""),
            "rebase": subprocess.CompletedProcess([], 1, "", "conflict"),
            "diff": subprocess.CompletedProcess([], 0, "pkg/a.py\npkg/b.py\n", ""),
        },
    )

    with pytest.raises(LaneBaseUpdateRefused, match="pkg/a.py, pkg/b.py"):
        lane_base_update.bring_lane_current(
            "/tmp/tree",
            branch="PRJ-9",
            target="main",
            project="yoke",
        )

    assert ("rebase", "--abort") in calls


def test_a_timed_out_rebase_aborts_and_returns_a_typed_recovery(monkeypatch):
    _clean_worktree(monkeypatch)
    calls = []

    def git(_checkout, *args, timeout=120):
        calls.append(args)
        if args[0] == "merge-base":
            return subprocess.CompletedProcess([], 1, "", "")
        if args == ("rebase", "origin/main"):
            raise subprocess.TimeoutExpired(args, timeout)
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(lane_base_update, "git", git)

    with pytest.raises(LaneBaseUpdateRefused, match="timed out after 600s") as raised:
        lane_base_update.bring_lane_current(
            "/tmp/tree", branch="PRJ-9", target="main", project="yoke"
        )

    assert ("rebase", "--abort") in calls
    assert "lane restored" in str(raised.value)
    assert isinstance(raised.value.__cause__, subprocess.TimeoutExpired)
