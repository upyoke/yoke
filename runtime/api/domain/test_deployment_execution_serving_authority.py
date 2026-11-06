"""Project owners drive external deployments through serving authority."""

from __future__ import annotations

from runtime.api.domain.deployment_execution_serving_authority_test_support import (LINEAGE as LINEAGE)

from runtime.api.domain.deployment_execution_serving_authority_test_support import (
    FLOW as FLOW,
    ITEM_ID as ITEM_ID,
    PROJECT as PROJECT,
    _call as _call,
    _project_owner as _project_owner,
    _session as _session,
    serving_plane as serving_plane,
)


from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.yoke_function_dispatch import dispatch


def test_project_only_owner_creates_pauses_resumes_fails_and_retries(
    serving_plane,
) -> None:
    client = serving_plane["client"]
    headers = serving_plane["owner_headers"]
    session_id = serving_plane["owner_session"]
    conn = serving_plane["conn"]
    actor_id = serving_plane["owner_id"]
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM actor_org_roles WHERE actor_id=%s", (actor_id,)
        ).fetchone()[0]
        == 0
    )

    created = _call(
        client,
        headers,
        session_id,
        "deployment_runs.create",
        payload={"project": PROJECT, "flow": FLOW, "release_lineage": LINEAGE},
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["result"]["run_id"]

    started = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.update",
        run_id=run_id,
        payload={"field": "status", "value": "executing"},
    )
    assert started.status_code == 200, started.text
    paused = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.update",
        run_id=run_id,
        payload={"field": "current_stage", "value": "approve-deploy"},
    )
    assert paused.status_code == 200, paused.text
    context = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.context",
        run_id=run_id,
    )
    assert context.status_code == 200, context.text
    assert context.json()["result"]["run"]["current_stage"] == "approve-deploy"

    resumed = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.update",
        run_id=run_id,
        payload={"field": "current_stage", "value": "hosted-release"},
    )
    assert resumed.status_code == 200, resumed.text
    failed = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.update",
        run_id=run_id,
        payload={"field": "status", "value": "failed"},
    )
    assert failed.status_code == 200, failed.text

    retried = _call(
        client,
        headers,
        session_id,
        "deployment_runs.create",
        payload={"project": PROJECT, "flow": FLOW, "retry_of": run_id},
    )
    assert retried.status_code == 200, retried.text
    retry_id = retried.json()["result"]["run_id"]
    assert retry_id != run_id
    retry_context = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.context",
        run_id=retry_id,
    )
    assert retry_context.status_code == 200, retry_context.text
    retry_run = retry_context.json()["result"]["run"]
    assert retry_run["status"] == "created"
    assert retry_run["release_lineage"] == LINEAGE
    assert retry_context.json()["result"]["stages"][1]["name"] == "approve-deploy"
    qa_ready = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.ephemeral_qa_ready",
        run_id=retry_id,
    )
    assert qa_ready.status_code == 200, qa_ready.text
    assert qa_ready.json()["result"]["ready"] is True

    local = dispatch(
        FunctionCallRequest(
            function="deployment_runs.execution.context",
            actor=ActorContext(actor_id=str(actor_id), session_id=session_id),
            target=TargetRef(kind="workflow_run", workflow_run_id=retry_id),
            payload={},
        ),
        ambient_session_id=session_id,
    )
    assert local.success is True
    assert local.result["run"]["id"] == retry_id


def test_project_only_owner_starts_item_bound_run_through_serving_handler(
    serving_plane,
) -> None:
    started = _call(
        serving_plane["client"],
        serving_plane["owner_headers"],
        serving_plane["owner_session"],
        "deployment_runs.start_for_item",
        public_ref="EXT-1",
        payload={
            "project": PROJECT,
            "flow": FLOW,
            "release_lineage": LINEAGE,
        },
    )
    assert started.status_code == 200, started.text
    result = started.json()["result"]
    assert result["public_ref"] == "EXT-1"
    assert "item_id" not in result
    assert result["project"] == PROJECT
    assert result["run_id"].startswith("run-")

    context = _call(
        serving_plane["client"],
        serving_plane["owner_headers"],
        serving_plane["owner_session"],
        "deployment_runs.execution.context",
        run_id=result["run_id"],
    )
    assert context.status_code == 200, context.text
    assert context.json()["result"]["members"][0]["public_ref"] == "EXT-1"


def test_project_owner_cannot_drive_another_projects_run(serving_plane) -> None:
    created = _call(
        serving_plane["client"],
        serving_plane["owner_headers"],
        serving_plane["owner_session"],
        "deployment_runs.create",
        payload={"project": PROJECT, "flow": FLOW, "release_lineage": LINEAGE},
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["result"]["run_id"]

    denied = _call(
        serving_plane["client"],
        serving_plane["other_headers"],
        serving_plane["other_session"],
        "deployment_runs.execution.context",
        run_id=run_id,
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "permission_denied"
