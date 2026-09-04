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
    authored_file_merge_preflight as file_line_preflight,
    qa_case_ci_entry_run as entry_run,
    qa_case_ci_lane,
    qa_case_ci_run,
    qa_case_ci_superseded_run,
)
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.verification_tree_binding import TreeIdentity

POST_REBASE_HEAD = "c" * 40


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """The runner's boundaries, with the lane live on its own branch."""
    checkout, recorder, artifact = wire_ci_case(tmp_path, monkeypatch)
    monkeypatch.setattr(
        qa_case_ci_lane,
        "checked_out_branch",
        lambda _c: "PRJ-9",
    )
    monkeypatch.setattr(qa_case_ci_lane, "ref_sha", lambda *_a: LANE_HEAD)
    monkeypatch.setattr(
        entry_run,
        "routes_through_merge_queue",
        lambda _p: True,
    )
    monkeypatch.setattr(entry_run, "base_branch", lambda _p, _c: "main")
    monkeypatch.setattr(
        file_line_preflight,
        "enforce_authored_file_limit",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        qa_case_ci_superseded_run,
        "force_cancel_if_rebased",
        lambda **_kwargs: "",
    )
    return checkout, recorder, artifact


def _run(checkout, *, dispatch, await_result, case=None, **kwargs):
    with mock.patch.object(qa_case_ci_lane, "dispatch_workflow", dispatch):
        with mock.patch.object(qa_case_ci_lane, "await_workflow", await_result):
            return qa_case_ci_run.execute_ci_case(
                case or ci_case(),
                checkout_path=checkout,
                **kwargs,
            )


def test_the_entry_run_is_the_verdict_and_nothing_is_dispatched(
    wired,
    monkeypatch,
):
    checkout, recorder, _ = wired
    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", lambda *a, **k: None)
    opened = mock.Mock(return_value="213")
    monkeypatch.setattr(entry_run, "open_landing_pull_request", opened)
    monkeypatch.setattr(
        entry_run,
        "find_entry_run",
        lambda **k: completed_run(LANE_HEAD),
    )
    dispatch = mock.Mock(side_effect=AssertionError("must not dispatch"))

    result = _run(
        checkout,
        dispatch=dispatch,
        await_result=mock.Mock(side_effect=AssertionError("must not await")),
    )

    assert result["verdict"] == "pass"
    assert result["ci_run_source"] == "adopted"
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

    def _open(_checkout, *, project, branch, target, lane_head, item_id):
        order.append(f"open-pr:{lane_head}")
        return "213"

    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", _rebase)
    monkeypatch.setattr(
        file_line_preflight,
        "enforce_authored_file_limit",
        lambda *_args, **_kwargs: order.append("file-line-preflight"),
    )
    monkeypatch.setattr(entry_run, "open_landing_pull_request", _open)
    monkeypatch.setattr(
        entry_run,
        "find_entry_run",
        lambda **k: completed_run(POST_REBASE_HEAD),
    )

    result = _run(
        checkout,
        dispatch=mock.Mock(side_effect=AssertionError("must not dispatch")),
        await_result=mock.Mock(side_effect=AssertionError("must not await")),
    )

    assert order == [
        "rebase",
        "file-line-preflight",
        f"open-pr:{POST_REBASE_HEAD}",
    ]
    assert result["verification_tree"]["head_sha"] == POST_REBASE_HEAD
    evidence = json.loads(recorder.payload("qa.run.add")["raw_result"])
    assert evidence["verification_tree"]["head_sha"] == POST_REBASE_HEAD


def test_file_line_refusal_stops_before_push_or_pull_request(wired, monkeypatch):
    checkout, recorder, _ = wired
    push = mock.Mock()
    opened = mock.Mock()
    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", lambda *a, **k: None)
    monkeypatch.setattr(qa_case_ci_lane, "push_lane", push)
    monkeypatch.setattr(entry_run, "open_landing_pull_request", opened)
    monkeypatch.setattr(
        file_line_preflight,
        "enforce_authored_file_limit",
        mock.Mock(side_effect=QaCaseExecutionError("shared.py: 357, limit 350")),
    )

    with pytest.raises(QaCaseExecutionError, match="shared.py"):
        qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)

    push.assert_not_called()
    opened.assert_not_called()
    assert recorder.calls == []


def test_rebased_gate_force_cancels_and_records_the_superseded_run(
    wired,
    monkeypatch,
):
    checkout, recorder, _ = wired
    head = {"sha": LANE_HEAD}
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.resolve_tree_identity",
        lambda tree: TreeIdentity(root=str(tree), head_sha=head["sha"]),
    )

    def _rebase(*_args, **_kwargs):
        head["sha"] = POST_REBASE_HEAD

    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", _rebase)
    monkeypatch.setattr(
        entry_run,
        "open_landing_pull_request",
        lambda *a, **k: "213",
    )
    monkeypatch.setattr(
        entry_run,
        "find_entry_run",
        lambda **k: completed_run(POST_REBASE_HEAD),
    )
    cancel = mock.Mock(return_value="88")
    monkeypatch.setattr(
        qa_case_ci_superseded_run,
        "force_cancel_if_rebased",
        cancel,
    )

    result = _run(
        checkout,
        dispatch=mock.Mock(side_effect=AssertionError("must not dispatch")),
        await_result=mock.Mock(side_effect=AssertionError("must not await")),
    )

    assert result["superseded_ci_run_id"] == "88"
    assert cancel.call_args.kwargs["previous_head_sha"] == LANE_HEAD
    assert cancel.call_args.kwargs["current_head_sha"] == POST_REBASE_HEAD
    evidence = json.loads(recorder.payload("qa.run.add")["raw_result"])
    assert evidence["superseded_ci_run_id"] == "88"


def test_an_entry_run_for_another_sha_falls_back_to_dispatch(wired, monkeypatch):
    checkout, _, _ = wired
    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", lambda *a, **k: None)
    monkeypatch.setattr(
        entry_run,
        "open_landing_pull_request",
        lambda *a, **k: "213",
    )
    monkeypatch.setattr(
        entry_run,
        "find_entry_run",
        lambda **k: completed_run("b" * 40),
    )
    dispatch = mock.Mock(return_value="42")

    result = _run(
        checkout,
        dispatch=dispatch,
        await_result=lambda **kwargs: (0, "success"),
    )

    dispatch.assert_called_once()
    assert result["ci_run_id"] == "42"
    assert result["ci_run_source"] == "dispatched"


def test_a_cancelled_entry_run_falls_back_to_dispatch(wired, monkeypatch):
    """A superseded entry run tested nothing, so it cannot wedge this sha."""
    checkout, _, _ = wired
    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", lambda *a, **k: None)
    monkeypatch.setattr(
        entry_run,
        "open_landing_pull_request",
        lambda *a, **k: "213",
    )
    monkeypatch.setattr(
        entry_run,
        "find_entry_run",
        lambda **k: completed_run(LANE_HEAD, "cancelled"),
    )
    dispatch = mock.Mock(return_value="42")

    result = _run(
        checkout,
        dispatch=dispatch,
        await_result=lambda **kwargs: (0, "success"),
    )

    dispatch.assert_called_once()
    assert result["verdict"] == "pass"
    assert result["ci_run_source"] == "dispatched"
    assert result["verification_tree"]["head_sha"] == LANE_HEAD


def test_no_entry_run_at_all_falls_back_to_dispatch(wired, monkeypatch):
    checkout, _, _ = wired
    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", lambda *a, **k: None)
    monkeypatch.setattr(
        entry_run,
        "open_landing_pull_request",
        lambda *a, **k: "213",
    )
    monkeypatch.setattr(entry_run, "find_entry_run", lambda **k: None)
    dispatch = mock.Mock(return_value="42")

    result = _run(
        checkout,
        dispatch=dispatch,
        await_result=lambda **kwargs: (0, "success"),
    )

    dispatch.assert_called_once()
    assert result["ci_run_id"] == "42"


def test_a_recorded_commit_still_opens_the_landing_pull_request(
    wired,
    monkeypatch,
):
    checkout, _, _ = wired
    monkeypatch.setattr(qa_case_ci_lane, "checked_out_branch", lambda _c: "main")
    monkeypatch.setattr(qa_case_ci_lane, "ref_sha", lambda _c, _ref: LANE_HEAD)
    rebase = mock.Mock(side_effect=AssertionError("must not rebase"))
    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", rebase)
    opened = mock.Mock(return_value="213")
    monkeypatch.setattr(entry_run, "open_landing_pull_request", opened)
    monkeypatch.setattr(
        entry_run,
        "find_entry_run",
        lambda **k: completed_run(LANE_HEAD),
    )
    dispatch = mock.Mock(side_effect=AssertionError("must not dispatch"))

    result = _run(
        checkout,
        dispatch=dispatch,
        await_result=mock.Mock(side_effect=AssertionError("must not await")),
        case=ci_case(lane_commit_sha=LANE_HEAD),
    )

    assert result["ci_run_source"] == "adopted"
    opened.assert_called_once()
    dispatch.assert_not_called()


def test_a_rebase_conflict_stops_the_gate_before_anything_is_published(
    wired,
    monkeypatch,
):
    checkout, recorder, _ = wired
    monkeypatch.setattr(
        entry_run,
        "rebase_lane_onto_base",
        mock.Mock(side_effect=QaCaseExecutionError("conflicts: pkg/a.py")),
    )
    push = mock.Mock()
    monkeypatch.setattr(qa_case_ci_lane, "push_lane", push)

    with pytest.raises(QaCaseExecutionError, match="pkg/a.py"):
        qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)

    push.assert_not_called()
    assert recorder.calls == []
