"""The queue project's gate: the landing pull request's entry run IS the run.

A project that lands through the merge queue rebases its lane, opens the
landing pull request, and takes the conclusion of the run GitHub mints for
it — so the suite executes once for entry instead of once for a dispatched
gate and again for entry. Everything here is about that substitution
holding: the order it happens in, the head it binds to, and the dispatch
fallback staying reachable when no entry run appears.
"""

from __future__ import annotations

import json
import subprocess
from unittest import mock

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import (
    ci_case,
    wire_ci_case,
)

from yoke_core.domain import (
    qa_case_ci_entry_run as entry_run,
    qa_case_ci_lane,
    qa_case_ci_run,
)
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.verification_tree_binding import TreeIdentity

LANE_HEAD = "a" * 40
POST_REBASE_HEAD = "c" * 40


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """The executor's boundaries, with the lane live on its own branch."""
    checkout, recorder, artifact = wire_ci_case(tmp_path, monkeypatch)
    monkeypatch.setattr(
        qa_case_ci_lane, "checked_out_branch", lambda _c: "PRJ-9",
    )
    monkeypatch.setattr(
        entry_run, "routes_through_merge_queue", lambda _p: True,
    )
    monkeypatch.setattr(entry_run, "base_branch", lambda _p, _c: "main")
    return checkout, recorder, artifact


def _completed(head_sha: str, conclusion: str = "success"):
    return qa_case_ci_lane.WorkflowRun(
        "77", "completed", conclusion,
        "https://github.test/actions/runs/77", head_sha,
    )


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


def test_a_cleaned_up_lane_keeps_the_dispatch_path(monkeypatch):
    routes = mock.Mock(side_effect=AssertionError("must not probe"))
    monkeypatch.setattr(entry_run, "routes_through_merge_queue", routes)

    assert entry_run.prepare_entry_run_lane(
        "/tmp/tree", project="yoke", branch="PRJ-9",
        lane_is_checked_out=False,
    ) is None


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
        monkeypatch, [None, None, pending, _completed(LANE_HEAD)],
        awaited=awaited,
    )

    assert run == _completed(LANE_HEAD)
    assert awaited.call_args.kwargs["run_id"] == "77"


def test_a_run_already_complete_is_returned_without_awaiting(monkeypatch):
    awaited = mock.Mock(side_effect=AssertionError("must not await"))

    run = _await_entry(monkeypatch, [_completed(LANE_HEAD)], awaited=awaited)

    assert run == _completed(LANE_HEAD)
    awaited.assert_not_called()


def test_no_entry_run_within_the_window_returns_none(monkeypatch):
    assert _await_entry(monkeypatch, []) is None


# The executor, end to end


def _run(checkout, *, dispatch, await_result, case=None, **kwargs):
    with mock.patch.object(qa_case_ci_lane, "dispatch_workflow", dispatch):
        with mock.patch.object(qa_case_ci_lane, "await_workflow", await_result):
            return qa_case_ci_run.execute_ci_case(
                case or ci_case(), checkout_path=checkout, **kwargs,
            )


def test_the_entry_run_is_the_verdict_and_nothing_is_dispatched(
    wired, monkeypatch,
):
    checkout, recorder, _ = wired
    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", lambda *a, **k: None)
    opened = mock.Mock(return_value="213")
    monkeypatch.setattr(entry_run, "open_landing_pull_request", opened)
    monkeypatch.setattr(
        entry_run, "await_entry_run", lambda **k: _completed(LANE_HEAD),
    )
    dispatch = mock.Mock(side_effect=AssertionError("must not dispatch"))

    result = _run(
        checkout, dispatch=dispatch,
        await_result=mock.Mock(side_effect=AssertionError("must not await")),
    )

    assert result["verdict"] == "pass"
    assert result["reused_pull_request_run"] is True
    assert result["run_url"] == "https://github.test/actions/runs/77"
    assert opened.call_args.kwargs["target"] == "main"
    dispatch.assert_not_called()
    assert recorder.payload("qa.run.complete")["verdict"] == "pass"


def test_the_lane_is_rebased_before_the_pull_request_opens(wired, monkeypatch):
    checkout, recorder, _ = wired
    order: list[str] = []
    head = {"sha": LANE_HEAD}
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.resolve_tree_identity",
        lambda tree: TreeIdentity(root=str(tree), head_sha=head["sha"]),
    )

    def _rebase(_checkout, *, branch, target, project):
        order.append("rebase")
        # The rebase is what moves the lane head the gate then binds to.
        head["sha"] = POST_REBASE_HEAD

    def _open(_checkout, *, project, branch, target, lane_head):
        order.append(f"open-pr:{lane_head}")
        return "213"

    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", _rebase)
    monkeypatch.setattr(entry_run, "open_landing_pull_request", _open)
    monkeypatch.setattr(
        entry_run, "await_entry_run", lambda **k: _completed(POST_REBASE_HEAD),
    )

    result = _run(
        checkout,
        dispatch=mock.Mock(side_effect=AssertionError("must not dispatch")),
        await_result=mock.Mock(side_effect=AssertionError("must not await")),
    )

    assert order == ["rebase", f"open-pr:{POST_REBASE_HEAD}"]
    assert result["verification_tree"]["head_sha"] == POST_REBASE_HEAD
    evidence = json.loads(recorder.payload("qa.run.add")["raw_result"])
    assert evidence["verification_tree"]["head_sha"] == POST_REBASE_HEAD


def test_an_entry_run_for_another_sha_falls_back_to_dispatch(wired, monkeypatch):
    checkout, _, _ = wired
    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", lambda *a, **k: None)
    monkeypatch.setattr(
        entry_run, "open_landing_pull_request", lambda *a, **k: "213",
    )
    monkeypatch.setattr(
        entry_run, "await_entry_run", lambda **k: _completed("b" * 40),
    )
    dispatch = mock.Mock(return_value="42")

    result = _run(
        checkout, dispatch=dispatch,
        await_result=lambda **kwargs: (0, "success"),
    )

    dispatch.assert_called_once()
    assert result["ci_run_id"] == "42"
    assert result["reused_pull_request_run"] is False


def test_no_entry_run_at_all_falls_back_to_dispatch(wired, monkeypatch):
    checkout, _, _ = wired
    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", lambda *a, **k: None)
    monkeypatch.setattr(
        entry_run, "open_landing_pull_request", lambda *a, **k: "213",
    )
    monkeypatch.setattr(entry_run, "await_entry_run", lambda **k: None)
    dispatch = mock.Mock(return_value="42")

    result = _run(
        checkout, dispatch=dispatch,
        await_result=lambda **kwargs: (0, "success"),
    )

    dispatch.assert_called_once()
    assert result["ci_run_id"] == "42"


def test_a_rebase_conflict_stops_the_gate_before_anything_is_published(
    wired, monkeypatch,
):
    checkout, recorder, _ = wired
    monkeypatch.setattr(
        entry_run, "rebase_lane_onto_base",
        mock.Mock(side_effect=QaCaseExecutionError("conflicts: pkg/a.py")),
    )
    push = mock.Mock()
    monkeypatch.setattr(qa_case_ci_lane, "push_lane", push)

    with pytest.raises(QaCaseExecutionError, match="pkg/a.py"):
        qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)

    push.assert_not_called()
    assert recorder.calls == []
