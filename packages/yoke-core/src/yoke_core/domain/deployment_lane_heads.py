"""Reconcile live lane observations before the driver asks for containment."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain import deploy_pipeline_control_plane as control_plane
from yoke_core.domain.lane_head_client import LaneHeadClientError, read_item_lanes
from yoke_core.domain.lane_head_record import reconcile_lane_head


_DRIVEN_RUN = ContextVar("deployment_lane_head_run", default="")


@contextmanager
def deployment_lane_head_scope(run_id: str):
    token = _DRIVEN_RUN.set(run_id)
    try:
        yield
    finally:
        _DRIVEN_RUN.reset(token)


def reconcile_member_lanes(run_id: str) -> None:
    """Refresh the lane settlement will read without modifying the run pin."""
    if _DRIVEN_RUN.get() != run_id:
        return
    for ref in control_plane.current_member_refs(run_id):
        try:
            project, lanes = read_item_lanes(TargetRef(kind="item", public_ref=ref))
        except LaneHeadClientError as exc:
            raise control_plane.DeploymentControlPlaneError(str(exc)) from exc
        if not lanes:
            continue
        # Active-lane containment reads the newest row with a recorded head.
        lane = max(lanes, key=lambda row: (row.get("commit_sha") is not None, row["id"]))
        _, error = reconcile_lane_head(project, lane)
        if error:
            raise control_plane.DeploymentControlPlaneError(f"{ref}: {error}")
