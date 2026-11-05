"""Deployment drivers preserve gates across HTTPS and local bootstrap."""

from __future__ import annotations

from runtime.api.domain.deploy_pipeline_https_execution_test_support import (
    FLOW as FLOW,
    LINEAGE as LINEAGE,
    PROJECT as PROJECT,
    _RelayResponse as _RelayResponse,
    _decision_request_id as _decision_request_id,
    _install_test_https as _install_test_https,
    _invoke as _invoke,
    _replace_flow as _replace_flow,
    serving_plane as serving_plane,
)


from yoke_core.domain import (
    deploy_pipeline,
    deploy_pipeline_failure,
)


def test_https_driver_preserves_approval_through_failure_retry(
    serving_plane, monkeypatch
) -> None:
    conn = serving_plane["conn"]
    _replace_flow(
        conn,
        [
            {"name": "preflight", "step_runner": "auto", "stage_kind": "execution"},
            {
                "name": "approve-deploy",
                "step_runner": "human-approval",
                "stage_kind": "execution",
                "approvals": {"roles": ["owner"], "actors": []},
            },
            {
                "name": "hosted-release",
                "step_runner": "health-check",
                "stage_kind": "execution",
            },
            {"name": "complete", "step_runner": "auto", "stage_kind": "execution"},
        ],
    )
    relayed = _install_test_https(monkeypatch, serving_plane)
    monkeypatch.setattr(deploy_pipeline, "resolve_project_checkout_path", lambda _p: "")
    monkeypatch.setattr(
        deploy_pipeline_failure, "_report_failure_trace", lambda _r: None
    )

    original_dispatch = deploy_pipeline.stage_receipt.dispatch_step_runner_with_receipt
    release_fails = {"once": True}

    def dispatch_stage(stage, **kwargs):
        if stage["name"] == "hosted-release":
            if release_fails["once"]:
                release_fails["once"] = False
                return 17, "simulated external runner failure"
            return 0, "simulated external runner success"
        return original_dispatch(stage, **kwargs)

    monkeypatch.setattr(
        deploy_pipeline.stage_receipt,
        "dispatch_step_runner_with_receipt",
        dispatch_stage,
    )
    created = _invoke(
        "deployment_runs.create",
        {"project": PROJECT, "flow": FLOW, "release_lineage": LINEAGE},
    )
    run_id = str(created["run_id"])

    assert (
        deploy_pipeline.run_pipeline(run_id) == deploy_pipeline.EXIT_AWAITING_APPROVAL
    )
    _invoke(
        "decision_requests.resolve",
        {"request_id": _decision_request_id(conn, run_id), "action": "approve"},
    )

    assert deploy_pipeline.run_pipeline(run_id) == deploy_pipeline.EXIT_STAGE_FAILED
    failed = conn.execute(
        "SELECT status,current_stage FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    assert tuple(failed) == ("failed", "hosted-release-failed")

    retry_id = str(
        _invoke(
            "deployment_runs.create",
            {"project": PROJECT, "flow": FLOW, "retry_of": run_id},
        )["run_id"]
    )
    assert (
        deploy_pipeline.run_pipeline(retry_id) == deploy_pipeline.EXIT_AWAITING_APPROVAL
    )
    _invoke(
        "decision_requests.resolve",
        {"request_id": _decision_request_id(conn, retry_id), "action": "approve"},
    )
    assert deploy_pipeline.run_pipeline(retry_id) == deploy_pipeline.EXIT_SUCCESS
    succeeded = conn.execute(
        "SELECT status,current_stage FROM deployment_runs WHERE id=%s",
        (retry_id,),
    ).fetchone()
    assert tuple(succeeded) == ("succeeded", "complete")
    assert {
        "deployment_runs.execution.context",
        "deployment_runs.execution.update",
        "deployment_runs.execution.qa_pending",
        "deployment_runs.stage_approval.evaluate",
    }.issubset(relayed)
