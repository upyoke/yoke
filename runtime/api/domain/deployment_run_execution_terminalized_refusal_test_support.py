# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.deployment_execution_serving_authority_test_support import (
    FLOW,
    PROJECT,
    _call,
    serving_plane,
)


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
