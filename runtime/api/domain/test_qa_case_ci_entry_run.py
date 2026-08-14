"""The queue project's gate, piece by piece: rebase, open, await.

A project that lands through the merge queue rebases its lane, opens the
landing pull request, and takes the conclusion of the run GitHub mints for
it — so the suite executes once for entry instead of once for a dispatched
gate and again for entry. This file covers each step on its own; the
sibling ``test_qa_case_ci_run_queue_gate`` drives them through the
runner.
"""

from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import LANE_HEAD, completed_run

from yoke_core.domain import qa_case_ci_entry_run as entry_run
from yoke_core.domain import qa_case_ci_lane
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


# Selecting the path


def test_a_project_outside_the_queue_keeps_the_dispatch_path(monkeypatch):
    monkeypatch.setattr(
        entry_run, "routes_through_merge_queue", lambda _p: False,
    )
    rebase = mock.Mock(side_effect=AssertionError("must not rebase"))
    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", rebase)

    assert entry_run.prepare_entry_run_lane(
        "/tmp/tree", project="widgets", branch="PRJ-9",
        lane_is_checked_out=True,
    ) is None


def test_a_recorded_commit_on_a_queue_project_still_takes_the_pr_path(
    monkeypatch,
):
    monkeypatch.setattr(
        entry_run, "routes_through_merge_queue", lambda _p: True,
    )
    monkeypatch.setattr(entry_run, "base_branch", lambda _p, _c: "main")
    rebase = mock.Mock(side_effect=AssertionError("must not rebase"))
    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", rebase)

    assert entry_run.prepare_entry_run_lane(
        "/tmp/tree", project="yoke", branch="PRJ-9",
        lane_is_checked_out=False,
    ) == "main"


def test_an_unreadable_capability_probe_keeps_the_dispatch_path(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.merge_queue_route_selection."
        "project_declares_merge_queue",
        lambda project: (False, "capability probe failed"),
    )

    assert entry_run.routes_through_merge_queue("yoke") is False


# Rebasing the lane


def _git_results(monkeypatch, results: dict[str, subprocess.CompletedProcess]):
    calls: list[tuple[str, ...]] = []

    def _fake_git(_checkout, *args, timeout=120):
        calls.append(args)
        return results.get(
            args[0], subprocess.CompletedProcess(list(args), 0, "", "")
        )

    monkeypatch.setattr(entry_run, "_git", _fake_git)
    return calls


def _clean_worktree(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.engines.merge_worktree_prepare_state._stash_classify_gate",
        lambda _ctx: None,
    )


def test_opening_the_pull_request_binds_this_machines_github_authority(
    monkeypatch,
):
    """Control-plane App credentials are absent here; the machine's are not."""
    import contextlib

    bound: list[str] = []

    @contextlib.contextmanager
    def _authority():
        bound.append("enter")
        yield
        bound.append("exit")

    monkeypatch.setattr(
        "yoke_cli.commands.merge_item_local_runtime."
        "machine_github_user_authority",
        _authority,
    )
    monkeypatch.setattr(
        "yoke_core.domain.merge_queue_landing_pull_request."
        "ensure_landing_pull_request",
        lambda _ctx, _ref, lane_head="": (
            ("213", None) if bound == ["enter"] else ("", "unbound")
        ),
    )

    pr_num = entry_run.open_landing_pull_request(
        "/tmp/tree", project="yoke", branch="PRJ-9", target="main",
        lane_head=LANE_HEAD,
    )

    assert pr_num == "213"
    assert bound == ["enter", "exit"]


def test_a_lane_behind_the_base_is_fetched_then_rebased(monkeypatch):
    _clean_worktree(monkeypatch)
    calls = _git_results(monkeypatch, {})

    entry_run.rebase_lane_onto_base(
        "/tmp/tree", branch="PRJ-9", target="main", project="yoke",
    )

    assert calls[0] == ("fetch", "--quiet", "--no-tags", "origin", "main")
    assert calls[1] == ("rebase", "origin/main")


def test_uncommitted_work_stops_the_gate_and_names_its_stash(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.engines.merge_worktree_prepare_state._stash_classify_gate",
        lambda _ctx: (4, "user-authored files at risk"),
    )
    rebased = _git_results(monkeypatch, {})

    with pytest.raises(QaCaseExecutionError, match="yoke-pre-rebase-PRJ-9"):
        entry_run.rebase_lane_onto_base(
            "/tmp/tree", branch="PRJ-9", target="main", project="yoke",
        )

    assert rebased == []


def test_a_conflicting_rebase_aborts_and_names_the_conflicted_paths(monkeypatch):
    _clean_worktree(monkeypatch)
    calls = _git_results(
        monkeypatch,
        {
            "rebase": subprocess.CompletedProcess([], 1, "", "conflict"),
            "diff": subprocess.CompletedProcess([], 0, "pkg/a.py\npkg/b.py\n", ""),
        },
    )

    with pytest.raises(QaCaseExecutionError, match="pkg/a.py, pkg/b.py"):
        entry_run.rebase_lane_onto_base(
            "/tmp/tree", branch="PRJ-9", target="main", project="yoke",
        )

    assert ("rebase", "--abort") in calls


# Waiting for the entry run


def _await_entry(monkeypatch, runs, *, awaited=None):
    """Drive ``await_entry_run`` over a scripted sequence of lookups."""
    pending = list(runs)
    monkeypatch.setattr(
        qa_case_ci_lane, "find_pull_request_run",
        lambda **kwargs: pending.pop(0) if pending else None,
    )
    monkeypatch.setattr(
        qa_case_ci_lane, "await_workflow",
        awaited or (lambda **kwargs: (0, "success")),
    )
    clock = {"now": 0.0}

    def _sleep(seconds):
        clock["now"] += seconds

    return entry_run.await_entry_run(
        project="yoke", repo="acme/widgets", workflow="ci.yml",
        head_sha=LANE_HEAD, timeout_seconds=60,
        sleep=_sleep, monotonic=lambda: clock["now"],
    )


def test_a_run_that_appears_late_is_waited_for_then_awaited(monkeypatch):
    pending = qa_case_ci_lane.WorkflowRun(
        "77", "in_progress", "", "https://github.test/actions/runs/77",
        LANE_HEAD,
    )
    awaited = mock.Mock(return_value=(0, "success"))

    run = _await_entry(
        monkeypatch, [None, None, pending, completed_run(LANE_HEAD)],
        awaited=awaited,
    )

    assert run == completed_run(LANE_HEAD)
    assert awaited.call_args.kwargs["run_id"] == "77"


def test_a_run_already_complete_is_returned_without_awaiting(monkeypatch):
    awaited = mock.Mock(side_effect=AssertionError("must not await"))

    run = _await_entry(monkeypatch, [completed_run(LANE_HEAD)], awaited=awaited)

    assert run == completed_run(LANE_HEAD)
    awaited.assert_not_called()


def test_no_entry_run_within_the_window_returns_none(monkeypatch):
    assert _await_entry(monkeypatch, []) is None
