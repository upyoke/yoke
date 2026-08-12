"""The CI-run executor: verdict from the run, evidence naming the tree.

Every case here is a project that does NOT route through the merge queue,
so this file is also the regression that the dispatch path is unchanged by
the entry-run gate its sibling ``test_qa_case_ci_entry_run`` covers.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import (
    ci_case as _case,
    wire_ci_case,
)

from yoke_core.domain import qa_case_ci_lane, qa_case_ci_run, qa_case_execution
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.verification_tree_binding import TreeBindingVerdict


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """Stub every boundary the executor crosses, and hand back the recorder."""
    return wire_ci_case(tmp_path, monkeypatch)


def _run(checkout, *, dispatch, await_result, case=None, **kwargs):
    with mock.patch.object(qa_case_ci_lane, "dispatch_workflow", dispatch):
        with mock.patch.object(qa_case_ci_lane, "await_workflow", await_result):
            return qa_case_ci_run.execute_ci_case(
                case or _case(), checkout_path=checkout, **kwargs,
            )


def test_no_pull_request_run_dispatches_and_records_the_result(wired):
    checkout, recorder, artifact = wired

    result = _run(
        checkout,
        dispatch=lambda **kwargs: "9182736",
        await_result=lambda **kwargs: (0, "success"),
    )

    assert result["verdict"] == "pass"
    assert result["case_outcome"] == "passed"
    assert result["runner_id"] == "ci_run"
    assert result["ci_run_id"] == "9182736"
    assert result["run_url"] == (
        "https://github.com/acme/widgets/actions/runs/9182736"
    )
    assert result["verification_tree"]["head_sha"] == "a" * 40

    added = recorder.payload("qa.run.add")
    assert added["performed_by"] == "ci_run"
    evidence = json.loads(added["raw_result"])
    assert evidence["execution_budget_seconds"] == (
        qa_case_ci_run.DEFAULT_CI_RUN_TIMEOUT_SECONDS
    )
    assert evidence["execution_budget_source"] == "registered_scope:full"
    assert evidence["run_url"] == result["run_url"]
    assert evidence["branch"] == "PRJ-9"
    assert evidence["workflow"] == "ci.yml"
    assert evidence["verification_tree"]["head_sha"] == "a" * 40
    assert recorder.payload("qa.run.complete")["verdict"] == "pass"


@pytest.mark.parametrize(
    ("conclusion", "verdict"), [("success", "pass"), ("failure", "fail")],
)
def test_completed_exact_pull_request_run_is_reused_without_dispatch(
    wired, conclusion, verdict,
):
    checkout, recorder, _ = wired
    covering = qa_case_ci_lane.WorkflowRun(
        "77", "completed", conclusion,
        "https://github.test/actions/runs/77", "a" * 40,
    )
    dispatch = mock.Mock(side_effect=AssertionError("must not dispatch"))
    await_result = mock.Mock(side_effect=AssertionError("must not await"))

    with mock.patch.object(
        qa_case_ci_lane, "find_pull_request_run",
        return_value=covering,
    ):
        result = _run(
            checkout, dispatch=dispatch, await_result=await_result,
        )

    assert result["verdict"] == verdict
    assert result["run_url"] == covering.html_url
    assert result["reused_pull_request_run"] is True
    evidence = json.loads(recorder.payload("qa.run.add")["raw_result"])
    assert evidence["verification_tree"]["head_sha"] == "a" * 40
    dispatch.assert_not_called()
    await_result.assert_not_called()


def test_pull_request_run_for_a_different_sha_dispatches(wired):
    checkout, _, _ = wired
    covering = qa_case_ci_lane.WorkflowRun(
        "77", "completed", "success",
        "https://github.test/actions/runs/77", "b" * 40,
    )
    dispatch = mock.Mock(return_value="42")
    with mock.patch.object(
        qa_case_ci_lane, "find_pull_request_run",
        return_value=covering,
    ):
        result = _run(
            checkout, dispatch=dispatch,
            await_result=lambda **kwargs: (0, "success"),
        )

    dispatch.assert_called_once()
    assert result["ci_run_id"] == "42"
    assert result["reused_pull_request_run"] is False


def test_failed_run_records_a_fail(wired):
    checkout, recorder, artifact = wired

    result = _run(
        checkout,
        dispatch=lambda **kwargs: "42",
        await_result=lambda **kwargs: (1, "failed: test (3.13)"),
    )

    assert result["verdict"] == "fail"
    assert result["case_outcome"] == "failed"
    assert recorder.payload("qa.run.complete")["verdict"] == "fail"
    # The captured artifact carries the poll output an operator reads.
    captured = artifact.read_text(encoding="utf-8")
    assert "failed: test (3.13)" in captured
    assert "https://github.com/acme/widgets/actions/runs/42" in captured


def test_dispatch_is_keyed_on_the_tree_under_test(wired):
    checkout, _, _ = wired
    seen: dict = {}

    def _dispatch(**kwargs):
        seen.update(kwargs)
        return "1"

    _run(checkout, dispatch=_dispatch, await_result=lambda **k: (0, "success"))

    assert seen["request_id"] == f"qa-case:41:{'a' * 40}"
    assert seen["branch"] == "PRJ-9"
    assert seen["workflow"] == "ci.yml"
    assert seen["repo"] == "acme/widgets"


def test_the_ci_budget_is_the_default_not_the_local_command_timeout(wired):
    checkout, _, _ = wired
    seen: dict = {}

    _run(
        checkout,
        dispatch=lambda **kwargs: seen.update(kwargs) or "1",
        await_result=lambda **kwargs: (0, "success"),
    )

    assert seen["timeout_seconds"] == (
        qa_case_ci_run.DEFAULT_CI_RUN_TIMEOUT_SECONDS
    )


def test_a_configured_timeout_wins_over_the_default(wired):
    checkout, _, _ = wired
    seen: dict = {}
    case = _case()
    case["method_config"]["timeout_seconds"] = 900

    _run(
        checkout,
        dispatch=lambda **kwargs: seen.update(kwargs) or "1",
        await_result=lambda **kwargs: (0, "success"),
        case=case,
    )

    assert seen["timeout_seconds"] == 900


def test_a_case_without_a_declared_workflow_fails_before_pushing(wired):
    checkout, recorder, artifact = wired
    case = _case()
    case["method_config"].pop("ci_workflow")

    with mock.patch.object(qa_case_ci_lane, "push_lane") as push:
        with pytest.raises(QaCaseExecutionError, match="ci_workflow"):
            qa_case_ci_run.execute_ci_case(case, checkout_path=checkout)

    push.assert_not_called()
    assert recorder.calls == []


def test_ci_runner_ignores_local_tree_binding(wired, monkeypatch):
    checkout, recorder, artifact = wired
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.evaluate_run",
        lambda **kwargs: TreeBindingVerdict(
            refusal="TREE-BINDING REFUSAL: wrong tree"
        ),
    )

    result = _run(
        checkout,
        dispatch=lambda **kwargs: "42",
        await_result=lambda **kwargs: (0, "success"),
    )
    assert result["verdict"] == "pass"
    assert recorder.payload("qa.run.complete")["verdict"] == "pass"


def test_cancelled_run_records_an_infrastructure_outcome(wired):
    checkout, recorder, _ = wired
    result = _run(
        checkout,
        dispatch=lambda **kwargs: "42",
        await_result=lambda **kwargs: (1, "failed:cancelled"),
    )
    assert result["verdict"] == "error"
    assert result["case_outcome"] == "infrastructure_transient"
    assert result["ci_conclusion"] == "cancelled"
    raw = json.loads(recorder.payload("qa.run.complete")["raw_result"])
    assert raw["failure_class"] == "infrastructure_transient"


def test_poll_error_records_a_run_before_refusing(wired):
    checkout, recorder, _ = wired

    def _raise(**kwargs):
        raise RuntimeError("relay unavailable")

    with pytest.raises(QaCaseExecutionError, match="recorded QA run #77"):
        _run(checkout, dispatch=lambda **kwargs: "42", await_result=_raise)
    assert recorder.payload("qa.run.complete")["verdict"] == "error"


def test_released_lane_uses_the_recorded_commit_without_tree_binding(
    wired, monkeypatch,
):
    checkout, _, _ = wired
    case = _case(lane_commit_sha="b" * 40)
    monkeypatch.setattr(qa_case_ci_lane, "checked_out_branch", lambda _c: "main")
    monkeypatch.setattr(qa_case_ci_lane, "ref_sha", lambda _c, ref: ref)
    pushed: dict = {}
    monkeypatch.setattr(
        qa_case_ci_lane, "push_lane",
        lambda checkout, branch, **kwargs: pushed.update(kwargs),
    )
    result = _run(
        checkout, case=case,
        dispatch=lambda **kwargs: "42",
        await_result=lambda **kwargs: (0, "success"),
    )
    assert pushed["source_ref"] == "b" * 40
    assert result["verification_tree"]["head_sha"] == "b" * 40


def test_shared_case_execution_routes_ci_run_to_this_runner():
    with mock.patch.object(
        qa_case_ci_run, "execute_ci_case", return_value={"verdict": "pass"},
    ) as runner:
        result = qa_case_execution.execute_case_context(
            _case(), checkout_path="/tmp/tree",
        )

    assert result == {"verdict": "pass"}
    assert runner.call_args.kwargs["checkout_path"] == "/tmp/tree"
