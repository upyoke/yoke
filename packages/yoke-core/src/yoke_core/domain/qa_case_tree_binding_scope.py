"""Whether the session's claimed lane is the tree a QA case is judged against.

:mod:`yoke_core.domain.verification_tree_binding` binds a verification run to
the worktree the session holds a claim on, because a green collected in the
main checkout while the claimed lane sits untouched reports on code nobody
changed. That reasoning needs the run to be *about* the claimed lane.

A deployment-run-scoped case is not. Its subject is the run: a candidate
revision already built, deployed, and observed at an endpoint the run's own
stage receipt recorded. No member's lane contributed to it, and no lane could
be the "right" tree for it, so binding it to whichever item claim the
executing session happens to hold refuses every routine invocation and sends
its owner to ``--allow-tree-mismatch`` — the flag reserved for a deliberate
cross-tree run, which then stops meaning anything. What the verdict is bound
to is the run and its observed target, and that is what this says instead.

The tree the command ran in is still recorded on the verdict either way, so
dropping the lane comparison loses no evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def session_lane_binds_case(case: Mapping[str, Any]) -> bool:
    """Return whether this case's verdict is about the session's own lane."""
    return case.get("item_id") is not None


def deployment_binding_notice(
    *,
    surface: str,
    case: Mapping[str, Any],
    tree: str,
) -> str:
    """Name the authority a deployment-run case's verdict IS bound to."""
    target = case.get("execution_target")
    target = target if isinstance(target, Mapping) else {}
    deployment = target.get("deployment")
    deployment = deployment if isinstance(deployment, Mapping) else {}
    endpoints = target.get("endpoints")
    endpoints = endpoints if isinstance(endpoints, Mapping) else {}
    run_id = str(deployment.get("run_id") or case.get("deployment_run_id") or "")
    stage = str(deployment.get("stage") or case.get("deployment_stage") or "")
    observed = str(
        target.get("observed_url") or endpoints.get("app_url") or ""
    ).strip()
    where = f" at {observed}" if observed else ""
    return (
        f"{surface}: deployment run {run_id!r} stage {stage!r} verifies the "
        f"candidate this run deployed{where}, not a checkout, so no claimed "
        f"worktree binds it. Running in '{tree}', which is recorded on the "
        "verdict."
    )


__all__ = ["deployment_binding_notice", "session_lane_binds_case"]
