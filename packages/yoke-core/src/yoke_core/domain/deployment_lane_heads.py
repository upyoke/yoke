"""Reconcile live lane observations before the driver asks for containment."""

from __future__ import annotations

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain import deploy_pipeline_control_plane as control_plane
from yoke_core.domain.lane_head_client import LaneHeadClientError, read_item_lanes
from yoke_core.domain.lane_head_record import reconcile_lane_head


def reconcile_member_lanes(run_id: str) -> None:
    """Refresh the lane settlement will read without modifying the run pin."""
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
