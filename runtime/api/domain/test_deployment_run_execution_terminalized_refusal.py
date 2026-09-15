"""A terminalized run refuses further execution-scoped writes.

The project's deploy-lock driver stays the same session across a whole
release pair; terminalizing a run (an operator canceling it, or the
pipeline itself failing it) must stop that SAME still-authorized driver
from later recording a stage receipt or QA verdict against it as if the
run were still live -- a late callback must not grant success to a run
that is already closed.
"""

from __future__ import annotations

from runtime.api.domain.test_deployment_execution_serving_authority import (
    FLOW,
    PROJECT,
    _call,
    serving_plane,
)
from yoke_core.domain.actor_permissions import ROLE_ADMIN, grant_actor_org_role

__all__ = ["serving_plane"]  # re-exported fixture; silence unused-import lints


def test_a_terminalized_run_refuses_further_execution_writes(serving_plane) -> None:
    client = serving_plane["client"]
    headers = serving_plane["owner_headers"]
    session_id = serving_plane["owner_session"]

    # Terminalizing is an org-admin act; the project-owner role serving_plane
    # otherwise grants is not enough on its own.
    grant_actor_org_role(
        serving_plane["conn"], actor_id=serving_plane["owner_id"], org_id=1,
        role_name=ROLE_ADMIN,
    )
    serving_plane["conn"].commit()

    created = _call(
        client,
        headers,
        session_id,
        "deployment_runs.create",
        payload={"project": PROJECT, "flow": FLOW, "release_lineage": "e" * 40},
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["result"]["run_id"]

    terminalized = _call(
        client,
        headers,
        session_id,
        "deployment_runs.terminalize",
        run_id=run_id,
        payload={"disposition": "cancelled", "reason": "superseded by a later run"},
    )
    assert terminalized.status_code == 200, terminalized.text

    for function_id, payload in (
        ("deployment_runs.execution.context", {}),
        (
            "deployment_runs.execution.update",
            {"field": "current_stage", "value": "approve-deploy"},
        ),
        (
            "deployment_runs.execution.qa_record",
            {"stage": "hosted-release", "verdict": "pass"},
        ),
        ("deployment_runs.execution.qa_seed", {}),
    ):
        response = _call(
            client, headers, session_id, function_id, run_id=run_id, payload=payload
        )
        assert response.status_code == 409, response.text
        body = response.json()
        assert body["success"] is False, (function_id, body)
        assert body["error"]["code"] == "run_terminalized", (function_id, body)
        assert "cancelled" in body["error"]["message"]
