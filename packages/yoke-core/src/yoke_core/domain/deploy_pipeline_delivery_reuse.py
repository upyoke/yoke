"""Ask whether a workflow stage's delivery already serves, before dispatching.

The control plane decides and records the reuse
(:mod:`deployment_run_delivery_reuse`); this module only asks, narrates the
answer, and keeps the previous behaviour where the serving build predates
the question: a skewed registry answer dispatches exactly as before.

A reused delivery still owes the fleet rehearsal a dispatch would run. The
control plane compares commits and promotion receipts only, so a replaced
box that serves nothing yet but whose last run succeeded would otherwise
skip the rehearsal entirely. The rehearsal runs first; a refusal stops the
stage exactly as it would stop a dispatch.
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Mapping, Optional

from yoke_core.domain import deploy_pipeline_control_plane as control_plane
from yoke_core.domain.control_plane_function_degradation import REGISTRY_SKEW_CODES
from yoke_core.domain.deployment_run_delivery_reuse import (
    DELIVERY_REUSE_FUNCTION_ID,
)


def reused_delivery(
    stage: Mapping[str, Any],
    *,
    run_id: str,
    fresh: bool,
    rehearse: Callable[[], tuple[int, str]],
) -> Optional[tuple[int, str]]:
    """The stage's outcome without dispatching, or ``None`` to dispatch.

    Only a ``github-actions-workflow`` stage that binds another project's
    source can be proven served, and ``--fresh`` always dispatches. Before
    asking, ``rehearse`` runs the fleet rehearsal the dispatch would run; its
    refusal is the stage's outcome.
    """
    if fresh or stage.get("step_runner") != "github-actions-workflow":
        return None
    if not stage.get("input_bindings"):
        return None
    stage_name = str(stage.get("name") or "")
    rehearsed_rc, rehearsal_refusal = rehearse()
    if rehearsed_rc != 0:
        return rehearsed_rc, rehearsal_refusal
    try:
        result = control_plane.reuse_delivery(run_id, stage_name=stage_name)
    except control_plane.DeploymentControlPlaneError as exc:
        if exc.code not in REGISTRY_SKEW_CODES:
            raise
        print(
            f"  {DELIVERY_REUSE_FUNCTION_ID} is not served yet (minimum serving "
            f"version next-release); dispatching stage '{stage_name}'",
            file=sys.stderr,
        )
        return None
    reused = str(result.get("reused_run_id") or "")
    if not reused:
        print(f"  Stage '{stage_name}' dispatches: {result.get('reason') or 'no reuse'}")
        return None
    print(
        f"  Stage '{stage_name}' reuses the delivery of run {reused}: the "
        "target already serves this run's commits, so nothing is dispatched"
    )
    return 0, f"stage {stage_name!r} reused the delivery of run {reused}"


__all__ = ["reused_delivery"]
