"""A cancelled run refuses further advancement, but stays readable.

Only ``cancelled`` is a deliberate, final stop (an operator or the
pipeline itself declaring "this work is superseded"); a still-legitimate
driver holding the project's deploy lock must not be able to record a new
status, a new stage, or a late stage-receipt completion against a run an
operator has since cancelled -- while diagnostics (reading the run's own
context) and the pipeline's own established failed-run retry-in-place
recovery stay untouched.
"""

from __future__ import annotations

from runtime.api.domain.test_deployment_execution_serving_authority import (
    FLOW,
    PROJECT,
    _call,
    serving_plane,
)

__all__ = ["serving_plane"]  # re-exported fixture; silence unused-import lints


def _create_and_cancel(client, headers, session_id) -> str:
    created = _call(
        client,
        headers,
        session_id,
        "deployment_runs.create",
        payload={"project": PROJECT, "flow": FLOW, "release_lineage": "e" * 40},
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
    return run_id


def _terminalize(client, headers, session_id, conn, actor_id, run_id: str) -> None:
    from yoke_core.domain.actor_permissions import ROLE_ADMIN, grant_actor_org_role

    grant_actor_org_role(conn, actor_id=actor_id, org_id=1, role_name=ROLE_ADMIN)
    conn.commit()
    terminalized = _call(
        client,
        headers,
        session_id,
        "deployment_runs.terminalize",
        run_id=run_id,
        payload={"disposition": "cancelled", "reason": "superseded by a later run"},
    )
    assert terminalized.status_code == 200, terminalized.text


def test_a_cancelled_run_refuses_further_status_and_stage_advancement(
    serving_plane,
) -> None:
    client = serving_plane["client"]
    headers = serving_plane["owner_headers"]
    session_id = serving_plane["owner_session"]

    run_id = _create_and_cancel(client, headers, session_id)
    _terminalize(
        client, headers, session_id, serving_plane["conn"], serving_plane["owner_id"], run_id
    )

    for field, value in (("status", "executing"), ("current_stage", "hosted-release")):
        response = _call(
            client,
            headers,
            session_id,
            "deployment_runs.execution.update",
            run_id=run_id,
            payload={"field": field, "value": value},
        )
        assert response.status_code == 400, response.text
        body = response.json()
        assert body["success"] is False, (field, body)
        assert "cancelled" in body["error"]["message"], (field, body)


def test_a_cancelled_runs_context_stays_readable(serving_plane) -> None:
    client = serving_plane["client"]
    headers = serving_plane["owner_headers"]
    session_id = serving_plane["owner_session"]

    run_id = _create_and_cancel(client, headers, session_id)
    _terminalize(
        client, headers, session_id, serving_plane["conn"], serving_plane["owner_id"], run_id
    )

    context = _call(
        client, headers, session_id, "deployment_runs.execution.context", run_id=run_id
    )
    assert context.status_code == 200, context.text
    assert context.json()["result"]["run"]["status"] == "cancelled"


def test_a_late_stage_receipt_completion_is_refused_once_cancelled(
    serving_plane,
) -> None:
    client = serving_plane["client"]
    headers = serving_plane["owner_headers"]
    session_id = serving_plane["owner_session"]

    run_id = _create_and_cancel(client, headers, session_id)
    staged = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.update",
        run_id=run_id,
        payload={"field": "current_stage", "value": "hosted-release"},
    )
    assert staged.status_code == 200, staged.text
    allocated = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.stage_receipt_allocate",
        run_id=run_id,
        payload={
            "stage_name": "hosted-release",
            "correlation_id": "corr-1",
            "target_kind": "run_preview",
            "executor": "github-actions",
        },
    )
    assert allocated.status_code == 200, allocated.text
    receipt_id = allocated.json()["result"]["receipt_id"]

    _terminalize(
        client, headers, session_id, serving_plane["conn"], serving_plane["owner_id"], run_id
    )

    completed = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.stage_receipt_complete",
        run_id=run_id,
        payload={
            "receipt_id": receipt_id,
            "correlation_id": "corr-1",
            "status": "ready",
            "target_name": "prod",
            "observed_release_lineage": "e" * 40,
        },
    )
    assert completed.status_code == 400, completed.text
    body = completed.json()
    assert body["success"] is False
    assert "no longer executing" in body["error"]["message"]
