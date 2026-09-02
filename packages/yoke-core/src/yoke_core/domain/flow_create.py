"""Insert one deployment flow.

Creation is the only flow write that has to invent identity, so it owns
the guards identity needs: a flow id is unique across the installation,
and one display name per project points at one flow id. The stages,
status, and deploy-target rules it enforces are the same ones every
later edit re-checks.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_helpers import iso8601_now, query_scalar
from yoke_core.domain.deployment_flow_state import (
    FLOW_STATUS_ACTIVE,
    validate_flow_status,
)
from yoke_core.domain.flow_target import resolve_flow_target
from yoke_core.domain.flow_validation import (
    require_human_approval_addresses,
    validate_stages,
)
from yoke_core.domain.project_identity import resolve_project


def cmd_create(
    conn,
    flow_id: str,
    project: str,
    name: str,
    description: str,
    stages_json: str,
    on_failure: str = "halt",
    target_tier: Optional[str] = None,
    environment: Optional[str] = None,
    done_description: Optional[str] = None,
    status: str = FLOW_STATUS_ACTIVE,
) -> str:
    """Insert one deployment flow.

    ``target_tier`` and ``environment`` travel together: a persistent flow
    names the registered environment it deploys to, an ephemeral flow
    deploys per-run substrate and names none, and a merge-only flow
    declares neither.
    """
    validate_stages(stages_json)
    require_human_approval_addresses(stages_json)
    validate_flow_status(status)
    target_environment_id = resolve_flow_target(
        conn,
        project=project,
        target_tier=target_tier,
        environment=environment,
    )
    ident = resolve_project(conn, project)
    assert ident is not None
    if _flow_exists(conn, flow_id):
        raise ValueError(f"deployment flow '{flow_id}' already exists")
    _assert_display_name_available(conn, ident.id, flow_id, name)
    conn.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, description, stages, on_failure, created_at, "
        "target_tier, target_environment_id, done_description, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            flow_id,
            ident.id,
            name,
            description,
            stages_json,
            on_failure,
            iso8601_now(),
            target_tier,
            target_environment_id,
            done_description,
            status,
        ),
    )
    conn.commit()
    return f"Created deployment flow: {flow_id}"


def _flow_exists(conn, flow_id: str) -> bool:
    return bool(
        query_scalar(
            conn,
            "SELECT COUNT(*) FROM deployment_flows WHERE id=%s",
            (flow_id,),
        )
    )


def _assert_display_name_available(
    conn,
    project_id: int,
    flow_id: str,
    name: str,
) -> None:
    """Keep one display name per project pointing at one flow id."""
    owner = query_scalar(
        conn,
        "SELECT id FROM deployment_flows WHERE project_id=%s AND name=%s",
        (project_id, name),
    )
    if owner is not None and str(owner) != flow_id:
        raise ValueError(
            f"display name '{name}' already belongs to deployment flow "
            f"'{owner}'; choose another name"
        )


__all__ = ["cmd_create"]
