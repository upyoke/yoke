"""The CI-run runner on a queue project: the entry run is the verdict.

Sibling of ``test_qa_case_ci_entry_run``, which covers the same gate's
pieces in isolation; this file drives them through
``execute_ci_case`` — the order they happen in, the head the verdict binds
to, and the dispatch fallback staying reachable.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import (
    LANE_HEAD,
    ci_case,
    completed_run,
    wire_ci_case,
)

from yoke_core.domain import (
    qa_case_ci_entry_run as entry_run,
    qa_case_ci_lane,
    qa_case_ci_run,
)
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.verification_tree_binding import TreeIdentity

POST_REBASE_HEAD = "c" * 40


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """The runner's boundaries, with the lane live on its own branch."""
    checkout, recorder, artifact = wire_ci_case(tmp_path, monkeypatch)
    monkeypatch.setattr(
        qa_case_ci_lane, "checked_out_branch", lambda _c: "PRJ-9",
    )
    monkeypatch.setattr(
        entry_run, "routes_through_merge_queue", lambda _p: True,
    )
    monkeypatch.setattr(entry_run, "base_branch", lambda _p, _c: "main")
    return checkout, recorder, artifact


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
        entry_run, "await_entry_run", lambda **k: completed_run(LANE_HEAD),
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
        entry_run, "await_entry_run", lambda **k: completed_run(POST_REBASE_HEAD),
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
        entry_run, "await_entry_run", lambda **k: completed_run("b" * 40),
    )
    dispatch = mock.Mock(return_value="42")

    result = _run(
        checkout, dispatch=dispatch,
        await_result=lambda **kwargs: (0, "success"),
    )

    dispatch.assert_called_once()
    assert result["ci_run_id"] == "42"
    assert result["reused_pull_request_run"] is False


def test_a_cancelled_entry_run_falls_back_to_dispatch(wired, monkeypatch):
    """A superseded entry run tested nothing, so it cannot wedge this sha."""
    checkout, _, _ = wired
    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", lambda *a, **k: None)
    monkeypatch.setattr(
        entry_run, "open_landing_pull_request", lambda *a, **k: "213",
    )
    monkeypatch.setattr(
        entry_run, "await_entry_run",
        lambda **k: completed_run(LANE_HEAD, "cancelled"),
    )
    dispatch = mock.Mock(return_value="42")

    result = _run(
        checkout, dispatch=dispatch,
        await_result=lambda **kwargs: (0, "success"),
    )

    dispatch.assert_called_once()
    assert result["verdict"] == "pass"
    assert result["reused_pull_request_run"] is False
    assert result["verification_tree"]["head_sha"] == LANE_HEAD


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
