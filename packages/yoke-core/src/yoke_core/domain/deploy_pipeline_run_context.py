"""Run-scoped context resolution and completion for the deploy pipeline.

Sibling of :mod:`yoke_core.domain.deploy_pipeline`: owns the pieces of a
pipeline execution that bracket the stage loop — resolving the project's
machine-local checkout and the flow's typed target up front, and marking
the run succeeded (with the member items' delivery-environment stamp) at
the end.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional, Tuple

from yoke_core.domain.deploy_pipeline_events import (
    emit_run_event as _emit_run_event,
)
from yoke_core.domain.deploy_pipeline_reporting import (
    _flow_db,
    _yoke_db,
)


def resolve_project_checkout_path(project: str) -> str:
    """Machine-config checkout path for *project*, warning when broken."""
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_checkout_locations import (
        checkout_for_project,
    )

    if not project:
        return ""
    conn = connect()
    try:
        checkout = checkout_for_project(conn, project)
    finally:
        conn.close()
    project_repo_path = str(checkout) if checkout is not None else ""
    if project_repo_path and not (
        Path(project_repo_path).expanduser() / ".git"
    ).exists():
        print(
            f"Warning: machine-config checkout for project '{project}' "
            f"at {project_repo_path} is missing or not a git checkout; "
            "stages that consult the project repository will fail — "
            "repair that projects entry in ~/.yoke/config.json",
            file=sys.stderr,
        )
    return project_repo_path


def resolve_flow_target(
    flow_id: str, sd: Optional[str] = None,
) -> Tuple[str, str]:
    """Return the flow's target tier and registered environment name."""
    flow_target = _flow_db("target", flow_id, sd=sd)
    tier, environment_name = (flow_target.split("|") + ["", ""])[:2]
    return tier, environment_name


def finalize_run_success(
    run_id: str,
    flow_id: str,
    project: str,
    member_items: List[str],
    target_tier: str,
    environment_name: str,
    sd: Optional[str] = None,
) -> None:
    """Stamp member items' delivery environment, then mark the run succeeded.

    Item stamps run first so a missed write cannot leave the run marked
    succeeded while the members stay unstamped.
    """
    # Auto-set deployed_to (item-bound; no-op for item-less runs). A
    # persistent run stamps the environment name; an ephemeral run has no
    # registered environment, so the tier is the delivery label.
    delivered_to = environment_name or target_tier
    if delivered_to and member_items:
        from yoke_core.domain.deployment_item_stamp import stamp_item_field

        for raw in member_items:
            stamp_item_field(int(raw), "deployed_to", delivered_to)
        print(f"Auto-set deployed_to={delivered_to} from flow {flow_id}")
    _yoke_db("runs", "update", run_id, "status", "succeeded", sd=sd)
    _emit_run_event(
        "DeploymentRunSucceeded", "completed",
        {
            "run_id": run_id,
            "flow": flow_id,
            "project": project,
            "target_environment": environment_name,
        },
        member_items=member_items, project=project, sd=sd,
    )


__all__ = [
    "finalize_run_success",
    "resolve_flow_target",
    "resolve_project_checkout_path",
]
