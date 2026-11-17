"""Dispatch-only observers join recorded standalone runs with the same payload."""
from dataclasses import replace
from unittest import mock

import pytest

from runtime.api.domain import test_qa_case_ci_run_queue_gate as queue_gate

from runtime.api.domain.qa_case_ci_test_helpers import LANE_HEAD, ci_case, in_flight_run
from yoke_core.domain import qa_case_ci_covering_run as covering
from yoke_core.domain import qa_case_ci_entry_run as entry
from yoke_core.engines import lane_base_update


wired = queue_gate.wired
_run = queue_gate._run

@pytest.mark.parametrize("inputs", [None, {}, {"browser_unit_tests": "true"}])
@pytest.mark.parametrize("resuming", [True, False])
def test_observer_only_joins_standalone_with_matching_recorded_inputs(
    wired, monkeypatch, inputs, resuming,
):
    checkout, recorder, _ = wired
    monkeypatch.setattr(entry, "workflow_event", lambda *a: "")
    monkeypatch.setattr(entry, "open_landing_pull_request", lambda *a, **k: "213")
    monkeypatch.setattr(lane_base_update, "bring_lane_current", lambda *a, **k: None)
    run = replace(in_flight_run(LANE_HEAD), dispatch_inputs=inputs)
    lookup = mock.Mock(side_effect=[run if resuming else None, run])
    monkeypatch.setattr(covering, "find_run_for_tree", lookup)
    dispatch = mock.Mock(return_value="9182736")
    await_result = mock.Mock(return_value=(0, "success"))
    result = _run(checkout, dispatch=dispatch, await_result=await_result)
    assert result["verdict"] == "pass"
    if inputs == {}:
        dispatch.assert_not_called()
        assert result["ci_run_source"] == "attached"
        assert await_result.call_args.kwargs["run_id"] == run.run_id
    else:
        dispatch.assert_called_once()
        assert result["ci_run_id"] != run.run_id
    assert all(call.kwargs["event"] == "" for call in lookup.call_args_list)
    assert recorder.payload("qa.run.complete")["verdict"] == "pass"


def test_declared_inputs_are_allowed_for_dispatch_only_queue_workflow(wired, monkeypatch):
    checkout, _, _ = wired
    monkeypatch.setattr(entry, "workflow_event", lambda *a: "")
    monkeypatch.setattr(entry, "open_landing_pull_request", lambda *a, **k: "213")
    run = replace(in_flight_run(LANE_HEAD), dispatch_inputs={"browser_unit_tests": "false"})
    monkeypatch.setattr(covering, "find_run_for_tree", lambda **k: run)
    case = ci_case()
    case["method_config"]["ci_workflow_inputs"] = dict(run.dispatch_inputs)
    dispatch = mock.Mock(side_effect=AssertionError("must join the recorded run"))
    result = _run(checkout, dispatch=dispatch,
                  await_result=mock.Mock(return_value=(0, "success")), case=case)
    assert result["ci_run_source"] == "attached"
