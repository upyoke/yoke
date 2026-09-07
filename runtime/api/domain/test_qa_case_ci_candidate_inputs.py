"""Candidate inputs travel with every dispatch and are never assumed.

A CI proof for an unpublished producer candidate carries two facts: the
commit CI checked out, and the candidate the run built against. The second
one rides ``method_config.ci_workflow_inputs``, so these cases follow it
through the three places a run is started — the gate's first dispatch, its
never-started redispatch, and the merge boundary — and pin the reuse rule
that keeps a run built against some other candidate from standing in.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import (
    LANE_HEAD,
    ci_case as _case,
    completed_run,
    in_flight_run,
    wire_ci_case,
)

from yoke_core.domain import (
    qa_case_ci_candidate_inputs as candidate_inputs,
    qa_case_ci_covering_run,
    qa_case_ci_entry_run,
    qa_case_ci_lane,
    qa_case_ci_never_started,
    qa_case_ci_run,
    qa_case_ci_superseded_run,
)
from yoke_core.domain.github_actions_run_stall import (
    CI_RUN_NEVER_STARTED_REASON,
)
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.qa_method_config_validation import (
    QaMethodConfigError,
    validate_method_config,
)

CANDIDATE = {"product_ref": "c" * 40}
STALL = (
    "stalled_dispatch waiting_on=pending_zero_jobs_stall "
    f"failure_reason={CI_RUN_NEVER_STARTED_REASON} status=pending jobs=0"
)


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    return wire_ci_case(tmp_path, monkeypatch)


def _candidate_case(**overrides):
    case = _case(**overrides)
    case["method_config"] = {
        **case["method_config"],
        candidate_inputs.CI_WORKFLOW_INPUTS_KEY: dict(CANDIDATE),
    }
    return case


# Declaring the inputs


def test_a_case_declares_its_candidate_and_the_config_keeps_it():
    config = validate_method_config(
        "command-ci",
        {
            "command": "python3 -m pytest tests/",
            "ci_workflow": "ci.yml",
            candidate_inputs.CI_WORKFLOW_INPUTS_KEY: {"product_ref": " abc "},
        },
    )

    assert config[candidate_inputs.CI_WORKFLOW_INPUTS_KEY] == {
        "product_ref": "abc",
    }


def test_a_case_that_declares_nothing_stores_no_inputs_key():
    """An ordinary CI case is byte-for-byte what it always was."""
    config = validate_method_config(
        "command-ci",
        {"command": "python3 -m pytest tests/", "ci_workflow": "ci.yml"},
    )

    assert candidate_inputs.CI_WORKFLOW_INPUTS_KEY not in config


@pytest.mark.parametrize(
    "declared",
    [
        {"yoke_dispatch_id": "yd-1234"},
        {"product_ref": 7},
        {"product_ref": ""},
        ["product_ref"],
    ],
)
def test_an_input_dispatch_cannot_honour_is_refused_at_configuration(declared):
    with pytest.raises(QaMethodConfigError):
        validate_method_config(
            "command-ci",
            {
                "command": "python3 -m pytest tests/",
                "ci_workflow": "ci.yml",
                candidate_inputs.CI_WORKFLOW_INPUTS_KEY: declared,
            },
        )


def test_a_queue_routed_project_is_refused_by_name(monkeypatch):
    """A pull_request run carries no inputs, so it can never prove one."""
    monkeypatch.setattr(
        qa_case_ci_entry_run, "routes_through_merge_queue", lambda _p: True,
    )

    with pytest.raises(QaCaseExecutionError) as excinfo:
        candidate_inputs.case_inputs(_candidate_case(), project="yoke")

    message = str(excinfo.value)
    assert "product_ref" in message
    assert "merge queue" in message
    assert candidate_inputs.CI_WORKFLOW_INPUTS_KEY in message


# The three dispatch paths


def test_the_gates_dispatch_carries_the_declared_candidate(wired):
    checkout, _recorder, _artifact = wired
    dispatch = mock.Mock(return_value="9182736")

    with mock.patch.object(qa_case_ci_lane, "dispatch_workflow", dispatch):
        with mock.patch.object(
            qa_case_ci_lane, "await_workflow", lambda **k: (0, "success"),
        ):
            result = qa_case_ci_run.execute_ci_case(
                _candidate_case(), checkout_path=checkout,
            )

    assert dispatch.call_args.kwargs["inputs"] == CANDIDATE
    assert result["verdict"] == "pass"


def test_the_recorded_evidence_names_the_candidate_it_proved(wired):
    checkout, recorder, _artifact = wired

    with mock.patch.object(
        qa_case_ci_lane, "dispatch_workflow", lambda **k: "9182736",
    ):
        with mock.patch.object(
            qa_case_ci_lane, "await_workflow", lambda **k: (0, "success"),
        ):
            qa_case_ci_run.execute_ci_case(
                _candidate_case(), checkout_path=checkout,
            )

    raw = json.loads(recorder.payload("qa.run.add")["raw_result"])
    assert raw["ci_workflow_inputs"] == CANDIDATE


def test_an_ordinary_case_records_no_candidate(wired):
    checkout, recorder, _artifact = wired

    with mock.patch.object(
        qa_case_ci_lane, "dispatch_workflow", lambda **k: "9182736",
    ):
        with mock.patch.object(
            qa_case_ci_lane, "await_workflow", lambda **k: (0, "success"),
        ):
            qa_case_ci_run.execute_ci_case(_case(), checkout_path=checkout)

    raw = json.loads(recorder.payload("qa.run.add")["raw_result"])
    assert raw["ci_workflow_inputs"] is None


def test_the_never_started_redispatch_carries_the_same_candidate(monkeypatch):
    pending = iter([(1, STALL), (0, "success")])
    monkeypatch.setattr(
        qa_case_ci_lane, "await_workflow", lambda **k: next(pending),
    )
    dispatch = mock.Mock(return_value="99")
    monkeypatch.setattr(qa_case_ci_lane, "dispatch_workflow", dispatch)
    monkeypatch.setattr(
        qa_case_ci_superseded_run, "force_cancel_run", mock.Mock(),
    )

    qa_case_ci_never_started.await_with_one_redispatch(
        requirement_id=41,
        project="yoke",
        repo="acme/widgets",
        workflow="ci.yml",
        branch="PRJ-9",
        head_sha=LANE_HEAD,
        run_id="77",
        run_url="https://github.test/actions/runs/77",
        source=qa_case_ci_covering_run.ATTACHED,
        timeout_seconds=1800,
        inputs=CANDIDATE,
    )

    assert dispatch.call_args.kwargs["inputs"] == CANDIDATE


def test_the_merge_boundary_reads_the_candidate_from_the_items_own_case():
    rows = {
        "rows": [
            {"id": 1, "method_config": {"ci_workflow": "other.yml"}},
            {
                "id": 2,
                "method_config": json.dumps(
                    {
                        "ci_workflow": "ci.yml",
                        candidate_inputs.CI_WORKFLOW_INPUTS_KEY: CANDIDATE,
                    }
                ),
            },
        ]
    }
    response = mock.Mock(success=True, result=rows, error=None)

    with mock.patch(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        return_value=response,
    ):
        resolved = candidate_inputs.item_inputs(item_id=9, workflow="ci.yml")

    assert resolved == CANDIDATE


def test_conflicting_declarations_refuse_rather_than_pick_one():
    rows = {
        "rows": [
            {
                "id": 1,
                "method_config": {
                    "ci_workflow": "ci.yml",
                    candidate_inputs.CI_WORKFLOW_INPUTS_KEY: CANDIDATE,
                },
            },
            {
                "id": 2,
                "method_config": {
                    "ci_workflow": "ci.yml",
                    candidate_inputs.CI_WORKFLOW_INPUTS_KEY: {
                        "product_ref": "d" * 40,
                    },
                },
            },
        ]
    }
    response = mock.Mock(success=True, result=rows, error=None)

    with mock.patch(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        return_value=response,
    ):
        with pytest.raises(QaCaseExecutionError) as excinfo:
            candidate_inputs.item_inputs(item_id=9, workflow="ci.yml")

    assert "different" in str(excinfo.value)


# Reuse


@pytest.mark.parametrize(
    "found",
    [completed_run(LANE_HEAD), in_flight_run(LANE_HEAD)],
)
def test_a_run_on_the_right_commit_cannot_prove_the_right_candidate(found):
    """GitHub never reports the inputs a run was posted with."""
    assert (
        qa_case_ci_covering_run.classify(
            found, head_sha=LANE_HEAD, required_inputs=CANDIDATE,
        )
        == qa_case_ci_covering_run.DISPATCHED
    )


@pytest.mark.parametrize(
    ("found", "expected"),
    [
        (completed_run(LANE_HEAD), qa_case_ci_covering_run.ADOPTED),
        (in_flight_run(LANE_HEAD), qa_case_ci_covering_run.ATTACHED),
    ],
)
def test_a_case_declaring_no_candidate_reuses_exactly_as_before(
    found, expected,
):
    assert (
        qa_case_ci_covering_run.classify(found, head_sha=LANE_HEAD) == expected
    )
    assert (
        qa_case_ci_covering_run.classify(
            found, head_sha=LANE_HEAD, required_inputs={},
        )
        == expected
    )


def test_the_gate_dispatches_past_a_run_it_cannot_attest(wired, monkeypatch):
    checkout, _recorder, _artifact = wired
    monkeypatch.setattr(
        qa_case_ci_covering_run,
        "find_run_for_tree",
        lambda **k: completed_run(LANE_HEAD),
    )
    dispatch = mock.Mock(return_value="9182736")

    with mock.patch.object(qa_case_ci_lane, "dispatch_workflow", dispatch):
        with mock.patch.object(
            qa_case_ci_lane, "await_workflow", lambda **k: (0, "success"),
        ):
            result = qa_case_ci_run.execute_ci_case(
                _candidate_case(), checkout_path=checkout,
            )

    assert result["ci_run_source"] == qa_case_ci_covering_run.DISPATCHED
    assert dispatch.call_args.kwargs["inputs"] == CANDIDATE
