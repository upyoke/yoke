"""Failed CI stays binding evidence until the checked inputs change."""

import json

import pytest

from runtime.api.merge_worktree_tests_ci_helpers import (
    bind_candidate_tree,
    existing_run,
    never,
    record_ci_runs,
    run_verification,
    stub_lane,
)
from yoke_core.domain import qa_case_ci_covering_run as covering_run


@pytest.mark.parametrize("conclusion", ["failure", "timed_out"])
def test_a_red_verdict_is_retained_without_dispatch(monkeypatch, tmp_path, conclusion):
    head = "2" * 40
    bind_candidate_tree(monkeypatch, tmp_path, head)
    stub_lane(
        monkeypatch,
        dispatch=never("must not dispatch a failed tree"),
        await_result=never("must not poll a completed verdict"),
        covering=existing_run(head, conclusion=conclusion),
    )
    recorded = record_ci_runs(monkeypatch)
    assert run_verification(tmp_path) == (1, "tests failed")
    assert recorded[0]["verdict"] == "fail"
    payload = json.loads(recorded[0]["raw_result"])
    assert payload["ci_run_source"] == covering_run.ADOPTED
    assert payload["ci_run_id"] == "88"
    assert payload["ci_conclusion"] == conclusion
