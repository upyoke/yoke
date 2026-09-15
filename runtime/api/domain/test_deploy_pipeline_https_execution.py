"""Deployment drivers preserve gates across HTTPS and local bootstrap."""

from __future__ import annotations

import io
import json
import urllib.error

from runtime.api.domain import (
    test_deployment_execution_serving_authority as serving_fixture,
)
from yoke_cli.transport import dispatcher as client_dispatcher
from yoke_cli.transport import https as https_transport
from yoke_cli.transport.https import HttpsConnection
from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import (
    control_plane_transport,
    deploy_pipeline,
    deploy_pipeline_control_plane,
    deploy_pipeline_failure,
)


serving_plane = serving_fixture.serving_plane
PROJECT = serving_fixture.PROJECT
FLOW = serving_fixture.FLOW
LINEAGE = serving_fixture.LINEAGE


class _RelayResponse(io.BytesIO):
    def __init__(self, body: bytes, headers) -> None:
        super().__init__(body)
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False


def _invoke(function_id: str, payload: dict, *, run_id: str = "") -> dict:
    target = (
        TargetRef(kind="workflow_run", workflow_run_id=run_id)
        if run_id
        else TargetRef(kind="global")
    )
    response = call_dispatcher(
        function_id=function_id,
        target=target,
        payload=payload,
    )
    assert response.success is True, response.error
    return dict(response.result or {})


def _replace_flow(conn, stages: list[dict]) -> None:
    conn.execute(
        "UPDATE deployment_flows SET stages=%s WHERE id=%s",
        (json.dumps(stages), FLOW),
    )
    conn.commit()


def _install_test_https(monkeypatch, plane) -> list[str]:
    client = plane["client"]
    session_id = plane["owner_session"]
    token = plane["owner_headers"]["Authorization"].split(" ", 1)[1]
    connection = HttpsConnection(
        api_url="https://external-control.example",
        token=token,
        env="external-https",
    )
    relayed: list[str] = []

    def open_no_redirect(request, timeout=None):
        del timeout
        payload = json.loads(request.data.decode("utf-8"))
        relayed.append(str(payload["function"]))
        response = client.post(
            "/v1/functions/call",
            headers={
                "Authorization": request.get_header("Authorization"),
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if response.status_code >= 400:
            raise urllib.error.HTTPError(
                request.full_url,
                response.status_code,
                response.reason_phrase,
                dict(response.headers),
                io.BytesIO(response.content),
            )
        return _RelayResponse(response.content, dict(response.headers))

    def local_dispatch_refused(*_args, **_kwargs):
        raise AssertionError("HTTPS deployment driver used local DB dispatch")

    monkeypatch.setattr(https_transport, "open_no_redirect", open_no_redirect)
    monkeypatch.setattr(
        https_transport,
        "resolve_https_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(https_transport, "record_outcome", lambda *_a, **_k: None)
    monkeypatch.setattr(client_dispatcher, "_call_local", local_dispatch_refused)
    monkeypatch.setattr(client_dispatcher, "_resolve_session_id", lambda: session_id)
    monkeypatch.setattr(
        control_plane_transport,
        "serving_control_plane_env",
        lambda: connection.env,
    )
    return relayed


def _decision_request_id(conn, run_id: str) -> int:
    row = conn.execute(
        "SELECT id FROM decision_requests WHERE subject_type='deployment_stage' "
        "AND subject_key=%s AND status='pending' ORDER BY id DESC LIMIT 1",
        (f"{run_id}:approve-deploy",),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _qa_statuses(conn, run_id: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT check_name,status FROM deployment_run_qa "
        "WHERE run_id=%s ORDER BY check_name",
        (run_id,),
    ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def test_https_driver_preserves_approval_and_qa_through_failure_retry(
    serving_plane, monkeypatch
) -> None:
    conn = serving_plane["conn"]
    _replace_flow(
        conn,
        [
            {"name": "preflight", "step_runner": "auto", "qa_kind": "preflight"},
            {
                "name": "approve-deploy",
                "step_runner": "human-approval",
                "qa_kind": "approval",
                "approvals": {"roles": ["owner"], "actors": []},
            },
            {
                "name": "hosted-release",
                "step_runner": "auto",
                "qa_kind": "release",
            },
            {"name": "complete", "step_runner": "auto"},
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
        if stage["name"] == "hosted-release" and release_fails["once"]:
            release_fails["once"] = False
            return 17, "simulated external runner failure"
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
    assert _qa_statuses(conn, run_id) == {
        "approve-deploy": "pending",
        "hosted-release": "pending",
        "preflight": "passed",
    }
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
    assert _qa_statuses(conn, run_id) == {
        "approve-deploy": "passed",
        "hosted-release": "failed",
        "preflight": "passed",
    }

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
    assert set(_qa_statuses(conn, retry_id).values()) == {"passed"}
    assert {
        "deployment_runs.execution.context",
        "deployment_runs.execution.update",
        "deployment_runs.execution.qa_seed",
        "deployment_runs.execution.qa_record",
        "deployment_runs.execution.qa_pending",
        "deployment_runs.stage_approval.evaluate",
    }.issubset(relayed)


def test_a_qa_write_failure_warns_but_never_reports_a_false_pass(
    serving_plane, monkeypatch
) -> None:
    """A QA-record write failure must not fabricate a passing verdict.

    Recording is eventually-consistent, non-blocking: the pipeline keeps
    going and the stage stays reported as completed. But nothing was
    actually persisted, so the projection this gate reads must still show
    the check unresolved — never silently "passed".
    """
    conn = serving_plane["conn"]
    _replace_flow(
        conn,
        [
            {"name": "preflight", "step_runner": "auto", "qa_kind": "preflight"},
            {"name": "complete", "step_runner": "auto"},
        ],
    )
    _install_test_https(monkeypatch, serving_plane)
    monkeypatch.setattr(deploy_pipeline, "resolve_project_checkout_path", lambda _p: "")

    original_record = deploy_pipeline_control_plane.record_qa_stage

    def failing_record(run_id, stage, verdict, **kwargs):
        if stage == "preflight":
            raise deploy_pipeline_control_plane.DeploymentControlPlaneError(
                "simulated qa_record write failure"
            )
        return original_record(run_id, stage, verdict, **kwargs)

    monkeypatch.setattr(
        deploy_pipeline_control_plane, "record_qa_stage", failing_record
    )
    run_id = str(
        _invoke(
            "deployment_runs.create",
            {"project": PROJECT, "flow": FLOW, "release_lineage": LINEAGE},
        )["run_id"]
    )

    # The write failure must not crash the driver — every stage still runs
    # to completion — but nothing was actually recorded for "preflight", so
    # the required-QA gate must hold the run back rather than reporting
    # success. A warning must never read back as a passing verdict.
    assert deploy_pipeline.run_pipeline(run_id) == deploy_pipeline.EXIT_AWAITING_QA
    unresolved = conn.execute(
        "SELECT status,current_stage FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    assert tuple(unresolved) != ("succeeded", "complete")
    statuses = _qa_statuses(conn, run_id)
    assert statuses.get("preflight") != "passed"
