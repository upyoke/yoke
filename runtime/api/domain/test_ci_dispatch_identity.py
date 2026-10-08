"""Effective producer inputs bind CI identity across all gate entry points."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from types import SimpleNamespace

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import LANE_HEAD, ci_case, wire_ci_case
from runtime.api.merge_worktree_tests_ci_helpers import (
    bind_candidate_tree,
    record_ci_runs,
    run_verification,
    stub_lane,
)
from yoke_cli.commands.adapters import github_actions_workflow as adapter
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import (
    ci_run_redispatch,
    qa_case_ci_lane,
    qa_case_ci_never_started,
    qa_case_ci_run,
)
from yoke_core.domain.yoke_function_dispatch_events import serialize_payload


@pytest.fixture
def dispatch_store(monkeypatch):
    """Use the real argument parser; record the actual typed dispatch payload."""
    intents = {}
    calls = []

    def call(function, payload, *, request_id, **kwargs):
        assert function == "github_actions.workflow.dispatch"
        _, checksum = serialize_payload(payload)
        calls.append((request_id, payload))
        fresh = request_id not in intents
        if fresh:
            intents[request_id] = (checksum, str(len(intents) + 100))
        recorded, run_id = intents[request_id]
        assert checksum == recorded, "idempotency_key_collision"
        return FunctionCallResponse(
            function=function,
            version="v1",
            success=True,
            result={"run_id": run_id, "dispatched": fresh},
        )

    def trigger(args, **kwargs):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = adapter.github_actions_trigger(
                [*args[1:], "--project", kwargs["project"]]
            )
        return SimpleNamespace(
            returncode=code, stdout=stdout.getvalue(), stderr=stderr.getvalue()
        )

    monkeypatch.setattr(adapter, "_call", call)
    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_github_workflow_dispatch.trigger_with_recovery_retries",
        trigger,
    )
    monkeypatch.setattr(ci_run_redispatch, "concluded_without_verdict", lambda **k: "")
    return intents, calls


def _dispatch(inputs=None, **overrides):
    return qa_case_ci_lane.dispatch_workflow(
        **{
            "project": "widgets",
            "repo": "acme/widgets",
            "workflow": "ci.yml",
            "branch": "candidate",
            "request_id": f"qa-case:41:{LANE_HEAD}",
            "timeout_seconds": 60,
            "inputs": inputs,
            **overrides,
        }
    )


def test_changed_producer_same_consumer_dispatches_and_identical_retry_rejoins(
    dispatch_store,
):
    first = _dispatch({"product_ref": "a" * 40, "mode": "full"})
    retry = _dispatch({"mode": "full", "product_ref": "a" * 40}, timeout_seconds=90)
    corrected = _dispatch({"product_ref": "b" * 40, "mode": "full"})
    assert first == retry
    assert corrected != first
    intents, calls = dispatch_store
    assert len(intents) == 2
    assert calls[0][0] == calls[1][0] != calls[2][0]
    assert all(LANE_HEAD in key for key, _ in calls)


@pytest.mark.parametrize(
    "change",
    [
        {"project": "other"},
        {"repo": "acme/other"},
        {"workflow": "other.yml"},
        {"branch": "other"},
        {"request_id": f"qa-case:41:{'d' * 40}"},
    ],
)
def test_every_dispatch_target_and_consumer_identity_is_bound(dispatch_store, change):
    assert _dispatch({"product_ref": "a" * 40}) != _dispatch(
        {"product_ref": "a" * 40}, **change
    )


def test_absent_and_empty_inputs_rejoin(dispatch_store):
    assert _dispatch() == _dispatch({}) == _dispatch(None)
    assert len(dispatch_store[0]) == 1


def test_no_verdict_chain_is_stable_and_remains_bound_to_inputs(
    dispatch_store, monkeypatch
):
    dead = _dispatch({"product_ref": "a" * 40})
    monkeypatch.setattr(
        ci_run_redispatch,
        "concluded_without_verdict",
        lambda **k: "cancelled" if k["run_id"] == dead else "",
    )
    replacement = _dispatch({"product_ref": "a" * 40})
    assert replacement != dead
    assert _dispatch({"product_ref": "a" * 40}) == replacement
    assert _dispatch({"product_ref": "b" * 40}) not in (dead, replacement)
    assert any(f":redispatch:{dead}" in key for key, _ in dispatch_store[1])


def test_initial_qa_keeps_requirement_and_consumer_when_producer_is_corrected(
    dispatch_store,
    tmp_path,
    monkeypatch,
):
    checkout, recorder, _ = wire_ci_case(tmp_path, monkeypatch)
    monkeypatch.setattr(qa_case_ci_lane, "await_workflow", lambda **k: (0, "success"))
    case = ci_case()
    runs = []
    for producer in ("a", "a", "b"):
        case["method_config"]["ci_workflow_inputs"] = {"product_ref": producer * 40}
        result = qa_case_ci_run.execute_ci_case(case, checkout_path=checkout)
        assert result["verdict"] == "pass"
        runs.append(result["ci_run_id"])
    assert runs[0] == runs[1] != runs[2]
    assert len(dispatch_store[0]) == 2
    assert len({key.split(":dispatch:")[0] for key, _ in dispatch_store[1]}) == 1


def test_never_started_retry_changes_identity_with_effective_producer(
    dispatch_store,
    monkeypatch,
):
    from yoke_core.domain.ci_job_outcome import CI_JOB_NOT_STARTED

    monkeypatch.setattr(qa_case_ci_never_started, "_record_wait", lambda *a, **k: None)
    monkeypatch.setattr(qa_case_ci_never_started, "_resolve_wait", lambda *a, **k: None)
    runs = []
    for producer in ("a", "a", "b"):
        outcomes = iter([(1, f"failed:{CI_JOB_NOT_STARTED}"), (0, "success")])
        monkeypatch.setattr(
            qa_case_ci_lane, "await_workflow", lambda **k: next(outcomes)
        )
        result = qa_case_ci_never_started.await_with_one_redispatch(
            requirement_id=41,
            project="widgets",
            repo="acme/widgets",
            workflow="ci.yml",
            branch="candidate",
            head_sha=LANE_HEAD,
            run_id="77",
            run_url="",
            source="dispatched",
            timeout_seconds=60,
            inputs={"product_ref": producer * 40},
        )
        assert result.exit_code == 0
        runs.append(result.run_id)
    assert runs[0] == runs[1] != runs[2]
    assert all(":never-started-retry:dispatch:" in key for key, _ in dispatch_store[1])


def test_merge_boundary_changed_producer_on_same_tree_dispatches_fresh(
    dispatch_store,
    tmp_path,
    monkeypatch,
):
    dispatch = qa_case_ci_lane.dispatch_workflow
    bind_candidate_tree(monkeypatch, tmp_path, LANE_HEAD)
    recorded = record_ci_runs(monkeypatch)
    for producer in ("a", "a", "b"):
        stub_lane(
            monkeypatch,
            dispatch=dispatch,
            await_result=lambda **k: (0, "success"),
            candidate={"product_ref": producer * 40},
        )
        assert run_verification(tmp_path) is None
    runs = [row["ci_run_id"] for row in recorded]
    assert runs[0] == runs[1] != runs[2]
    assert all(key.startswith("merge-gate:") for key, _ in dispatch_store[1])
