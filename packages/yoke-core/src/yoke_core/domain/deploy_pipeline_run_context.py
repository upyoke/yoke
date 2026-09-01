"""Run-scoped context resolution and completion for the deploy pipeline.

Sibling of :mod:`yoke_core.domain.deploy_pipeline`: owns the pieces of a
pipeline execution that bracket the stage loop — resolving the project's
machine-local checkout and the flow's typed target up front, and marking
the run succeeded (with the member items' delivery-environment stamp) at
the end.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

from yoke_contracts.deployment_itemless_teaching import (
    FINALIZATION_PENDING_PREFIX,
)
from yoke_core.domain.deploy_pipeline_events import (
    emit_run_event as _emit_run_event,
)
from yoke_core.domain.deploy_pipeline_reporting import (
    _flow_db,
)
from yoke_core.domain import deploy_pipeline_run_updates as run_updates

EXIT_FINALIZATION_PENDING = 4
_STATUS_WRITE_BACKOFF_SECONDS = (1.0, 2.0)
_STATUS_WRITE_RETRY_ERRORS = (run_updates.DeployPipelineRunUpdateError,)


class RunFinalizationPending(RuntimeError):
    """Stages finished; the succeeded status write did not land."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(
            f"{FINALIZATION_PENDING_PREFIX} — re-drive {run_id} to finalize"
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
    if (
        project_repo_path
        and not (Path(project_repo_path).expanduser() / ".git").exists()
    ):
        print(
            f"Warning: machine-config checkout for project '{project}' "
            f"at {project_repo_path} is missing or not a git checkout; "
            "stages that consult the project repository will fail — "
            "repair that projects entry in ~/.yoke/config.json",
            file=sys.stderr,
        )
    return project_repo_path


def resolve_flow_target(
    flow_id: str,
    sd: Optional[str] = None,
) -> Tuple[str, str]:
    """Return the flow's target tier and registered environment name."""
    flow_target = _flow_db("target", flow_id, sd=sd)
    tier, environment_name = (flow_target.split("|") + ["", ""])[:2]
    return tier, environment_name


def _update_run_succeeded(run_id: str, sd: Optional[str]) -> None:
    """Write ``status=succeeded``, retrying the idempotent update."""
    delays = (0.0, *_STATUS_WRITE_BACKOFF_SECONDS)
    last_exc: BaseException | None = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        try:
            run_updates.update_run_field(run_id, "status", "succeeded")
            return
        except _STATUS_WRITE_RETRY_ERRORS as exc:
            last_exc = exc
    assert last_exc is not None
    raise RunFinalizationPending(run_id) from last_exc


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
    _update_run_succeeded(run_id, sd)
    _emit_run_event(
        "DeploymentRunSucceeded",
        "completed",
        {
            "run_id": run_id,
            "flow": flow_id,
            "project": project,
            "target_environment": environment_name,
        },
        member_items=member_items,
        project=project,
        sd=sd,
    )


def complete_run_finalization(
    run_id: str,
    flow_id: str,
    project: str,
    member_items: List[str],
    target_tier: str,
    environment_name: str,
    sd: Optional[str] = None,
) -> int:
    """Land the succeeded stamp after stages; 4 when only that write is pending."""
    try:
        finalize_run_success(
            run_id,
            flow_id,
            project,
            member_items,
            target_tier,
            environment_name,
            sd=sd,
        )
    except RunFinalizationPending as pending:
        print(str(pending), file=sys.stderr)
        return EXIT_FINALIZATION_PENDING
    print(f"Pipeline complete for run {run_id}")
    return 0


__all__ = [
    "EXIT_FINALIZATION_PENDING",
    "RunFinalizationPending",
    "complete_run_finalization",
    "finalize_run_success",
    "resolve_flow_target",
    "resolve_project_checkout_path",
]
