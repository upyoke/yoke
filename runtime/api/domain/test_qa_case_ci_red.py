"""A failed test run cannot be replaced by unchanged-input QA."""

from unittest import mock

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import (
    LANE_HEAD,
    ci_case,
    completed_run,
    wire_ci_case,
)
from yoke_core.domain import qa_case_ci_covering_run as covering
from yoke_core.domain import qa_case_ci_lane, qa_case_ci_run


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    return wire_ci_case(tmp_path, monkeypatch)


@pytest.mark.parametrize("conclusion", ["failure", "timed_out"])
def test_red_verdict_is_adopted_without_dispatch_or_poll(
    wired, monkeypatch, conclusion
):
    checkout, recorder, _ = wired
    prior = completed_run(LANE_HEAD, conclusion)
    monkeypatch.setattr(covering, "find_run_for_tree", lambda **kwargs: prior)
    dispatch = mock.Mock(side_effect=AssertionError("must not dispatch"))
    poll = mock.Mock(side_effect=AssertionError("must not poll"))
    monkeypatch.setattr(qa_case_ci_lane, "dispatch_workflow", dispatch)
    monkeypatch.setattr(qa_case_ci_lane, "await_workflow", poll)
    result = qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)
    assert result["verdict"] == "fail"
    assert result["ci_run_id"] == prior.run_id
    assert result["ci_conclusion"] == conclusion
    assert recorder.payload("qa.run.complete")["verdict"] == "fail"
    assert covering.dispatch_request_id("key", LANE_HEAD, prior) == "key"
    dispatch.assert_not_called()
    poll.assert_not_called()
