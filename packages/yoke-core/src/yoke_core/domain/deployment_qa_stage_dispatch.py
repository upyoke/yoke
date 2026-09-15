"""Deployment runner dispatch for scoped QA stages.

Materializing and gating a scoped QA stage reads/writes qa_requirements and
qa_runs on the database that serves this control plane. The deploy driver
runs wherever an operator (or a headless deploy runner) started it, often
with no local database authority at all — an ordinary project deploy works
over HTTPS only. So this always dispatches to the serving build rather than
connecting here, mirroring
``deployment_stage_approval_dispatch.dispatch_deployment_stage_approval``.
``materialize_and_gate_deployment_qa_stage`` is the server-side
implementation the relayed handler calls; it takes a live connection the
caller already holds.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION = "deployment_runs.qa_stage.dispatch"


def materialize_and_gate_deployment_qa_stage(
    conn: Any, stage: Mapping[str, Any], *, run_id: str
) -> tuple[int, str]:
    """Materialize and gate every subject; ``-4`` means durable QA wait.

    Server-side implementation: the caller already holds a connection to
    the database that serves this control plane.
    """
    from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
    from yoke_core.domain.deployment_qa_stage_materialization import (
        materialize_deployment_qa_stage,
    )

    if stage.get("scope") == "item":
        rows = conn.execute(
            "SELECT item_id FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
            (run_id,),
        ).fetchall()
        members = [
            int(row["item_id"] if hasattr(row, "keys") else row[0]) for row in rows
        ]
        if not members:
            return 1, "item-scoped QA stage has no attached run members"
    else:
        members = [None]
    waiting: list[str] = []
    for member in members:
        try:
            existing = conn.execute(
                "SELECT 1 FROM qa_requirements WHERE deployment_run_id=%s "
                "AND deployment_stage=%s "
                "AND COALESCE(deployment_member_item_id,0)=%s "
                "AND method_id IS NOT NULL LIMIT 1",
                (run_id, str(stage["name"]), member or 0),
            ).fetchone()
            if existing is None:
                materialize_deployment_qa_stage(
                    conn,
                    deployment_run_id=run_id,
                    deployment_stage=str(stage["name"]),
                    deployment_member_item_id=member,
                )
            status = deployment_qa_stage_status(
                conn,
                run_id=run_id,
                stage_name=str(stage["name"]),
                member_item_id=member,
            )
        except (LookupError, ValueError) as exc:
            return 1, str(exc)
        if not status["accepted"]:
            label = f"member {member}" if member is not None else "run"
            waiting.extend(f"{label}: {reason}" for reason in status["reasons"])
    if waiting:
        return -4, "; ".join(waiting)
    return 0, ""


def dispatch_deployment_qa_stage(
    stage: Mapping[str, Any], *, run_id: str
) -> tuple[int, str]:
    """Deployment step-runner adapter for one scoped QA stage.

    Always dispatches to the build that SERVES this control plane's
    database — the driver may hold no local database authority at all.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.domain.control_plane_transport import serving_authority

    try:
        result = serving_authority(
            DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
            {"stage": dict(stage)},
            TargetRef(kind="workflow_run", workflow_run_id=run_id),
        )
    except RuntimeError as exc:
        return 1, (
            f"deployment QA stage {stage.get('name')!r} could not be "
            f"dispatched on the serving control plane: {exc}"
        )
    return int(result.get("code", 1)), str(result.get("message") or "")


__all__ = [
    "DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION",
    "dispatch_deployment_qa_stage",
    "materialize_and_gate_deployment_qa_stage",
]
