"""The CI gate's queue-entry path, piece by piece.

A merge-queue lane is brought current (``test_lane_base_update_steps``),
publishes once, and takes its pull-request entry run as the verdict. The assembled path is covered by the queue-gate tests.
"""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import LANE_HEAD, completed_run

from yoke_core.domain import lane_base_update, qa_case_ci_covering_run
from yoke_core.domain import qa_case_ci_entry_run as entry_run
from yoke_core.domain import qa_case_ci_lane
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


def test_a_project_outside_the_queue_keeps_the_dispatch_path(monkeypatch):
    monkeypatch.setattr(
        entry_run,
        "routes_through_merge_queue",
        lambda _p: False,
    )
    monkeypatch.setattr(entry_run, "base_branch", lambda _p, _c: "main")
    rebase = mock.Mock()
    monkeypatch.setattr(lane_base_update, "bring_lane_current", rebase)

    assert (
        entry_run.prepare_ci_lane(
            "/tmp/tree",
            project="widgets",
            branch="PRJ-9",
            lane_is_checked_out=True,
        )
        is None
    )
    assert rebase.call_count == 1


def test_a_recorded_commit_on_a_queue_project_still_takes_the_pr_path(
    monkeypatch,
):
    monkeypatch.setattr(
        entry_run,
        "routes_through_merge_queue",
        lambda _p: True,
    )
    monkeypatch.setattr(entry_run, "base_branch", lambda _p, _c: "main")
    rebase = mock.Mock(side_effect=AssertionError("must not rebase"))
    monkeypatch.setattr(lane_base_update, "bring_lane_current", rebase)

    assert (
        entry_run.prepare_ci_lane(
            "/tmp/tree",
            project="yoke",
            branch="PRJ-9",
            lane_is_checked_out=False,
        )
        == "main"
    )


def test_a_refused_lane_update_stops_the_gate_with_its_named_reason(monkeypatch):
    monkeypatch.setattr(entry_run, "routes_through_merge_queue", lambda _p: True)
    monkeypatch.setattr(entry_run, "base_branch", lambda _p, _c: "main")
    monkeypatch.setattr(
        lane_base_update,
        "bring_lane_current",
        mock.Mock(
            side_effect=lane_base_update.LaneBaseUpdateRefused(
                "lane_rebase_conflict: pkg/a.py"
            )
        ),
    )

    with pytest.raises(QaCaseExecutionError, match="lane_rebase_conflict: pkg/a.py"):
        entry_run.prepare_ci_lane(
            "/tmp/tree", project="yoke", branch="PRJ-9", lane_is_checked_out=True
        )


def test_an_unreadable_capability_probe_keeps_the_dispatch_path(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.merge_queue_route_selection.project_declares_merge_queue",
        lambda project: (False, "capability probe failed"),
    )

    assert entry_run.routes_through_merge_queue("yoke") is False


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
        "yoke_cli.commands.merge_item_local_runtime.machine_github_user_authority",
        _authority,
    )
    monkeypatch.setattr(
        "yoke_core.domain.merge_queue_landing_pull_request.ensure_landing_pull_request",
        lambda _ctx, _ref, lane_head="", item_public_ref="": (
            ("213", None) if bound == ["enter"] and item_public_ref else ("", "unbound")
        ),
    )

    pr_num = entry_run.open_landing_pull_request(
        "/tmp/tree",
        project="yoke",
        branch="PRJ-9",
        target="main",
        lane_head=LANE_HEAD,
        public_ref=f"ITEM-{7}",
    )

    assert pr_num == "213"
    assert bound == ["enter", "exit"]


# Waiting for the entry run to appear


def _find_entry(monkeypatch, runs):
    """Drive ``find_entry_run`` over a scripted sequence of lookups."""
    pending = list(runs)
    monkeypatch.setattr(
        qa_case_ci_covering_run,
        "find_run_for_tree",
        lambda **kwargs: pending.pop(0) if pending else None,
    )
    clock = {"now": 0.0}

    def _sleep(seconds):
        clock["now"] += seconds

    return entry_run.find_entry_run(
        requirement_id=41,
        project="yoke",
        repo="acme/widgets",
        workflow="ci.yml",
        head_sha=LANE_HEAD,
        timeout_seconds=60,
        sleep=_sleep,
        monotonic=lambda: clock["now"],
    )


@pytest.mark.parametrize("absences", [0, 2])
def test_the_run_is_returned_in_whatever_state_it_appears_in(
    monkeypatch,
    absences,
):
    """Concluding it is the runner's job; appearing is this one's."""
    pending = qa_case_ci_lane.WorkflowRun(
        "77",
        "in_progress",
        "",
        "https://github.test/actions/runs/77",
        LANE_HEAD,
    )
    scripted = [None] * absences

    assert _find_entry(monkeypatch, [*scripted, pending]) == pending
    assert _find_entry(
        monkeypatch,
        [*scripted, completed_run(LANE_HEAD)],
    ) == completed_run(LANE_HEAD)


def test_the_entry_lookup_asks_only_about_pull_request_runs(monkeypatch):
    """A dispatch green can never satisfy this project's required check."""
    seen: dict = {}

    def _lookup(**kwargs):
        seen.update(kwargs)
        return completed_run(LANE_HEAD)

    monkeypatch.setattr(qa_case_ci_covering_run, "find_run_for_tree", _lookup)
    entry_run.find_entry_run(
        requirement_id=41,
        project="yoke",
        repo="acme/widgets",
        workflow="ci.yml",
        head_sha=LANE_HEAD,
        timeout_seconds=60,
    )

    assert seen["event"] == "pull_request"
    assert seen["head_sha"] == LANE_HEAD


def test_no_entry_run_within_the_window_returns_none(monkeypatch):
    assert _find_entry(monkeypatch, []) is None
