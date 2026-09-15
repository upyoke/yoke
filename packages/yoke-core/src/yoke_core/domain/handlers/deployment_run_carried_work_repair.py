"""Re-derive one run's carried work after the comparison became answerable.

Carried work is written once and then frozen, which is right for a record
that was actually computed and wrong for one that only recorded that nobody
could compute it. A run completed on a control plane that could not read the
project's source carries such a record forever, so this repair replaces
exactly that case: a stored result whose comparison never ran, and only when
a fresh derivation can answer it now.

It never rewrites a record that was derived, never invents attribution, and
never reports success when the fresh answer is still unknown — the refusal
names the reason the second attempt failed so the missing authority is the
thing that gets fixed.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.deployment_run_carried_work import (
    CARRIED_WORK_FIELD,
    derive_carried_work_safely,
    parse_carried_work,
)
from yoke_core.domain.handlers.deployment_common import error, run_id
from yoke_core.domain.json_helper import dumps_compact


class DeploymentRunCarriedWorkRepairRequest(BaseModel):
    run_id: Optional[str] = None


class DeploymentRunCarriedWorkRepairResponse(BaseModel):
    run_id: str
    repaired: bool
    previous_reason: str
    carried_work: dict


def _derivation(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    derivation = payload.get("derivation")
    return dict(derivation) if isinstance(derivation, dict) else {}


def handle_deployment_run_carried_work_repair(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Replace one unknown carried-work record with a derived one."""
    resolved_run_id = run_id(request, "deployment_runs.carried_work.repair")
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id

    from yoke_core.domain.db_helpers import connect

    conn = connect(None)
    try:
        row = conn.execute(
            f"SELECT {CARRIED_WORK_FIELD} FROM deployment_runs WHERE id=%s",
            (resolved_run_id,),
        ).fetchone()
        if row is None:
            return error(
                "not_found",
                f"deployment run {resolved_run_id!r} not found",
                jsonpath="$.target.workflow_run_id",
            )
        stored = parse_carried_work(row[0] if not hasattr(row, "keys") else row[CARRIED_WORK_FIELD])
        if stored is None:
            return error(
                "carried_work_absent",
                f"deployment run {resolved_run_id!r} has no carried-work record to "
                "repair; completing the run derives one",
                jsonpath="$.target.workflow_run_id",
            )
        previous = _derivation(stored)
        if bool(previous.get("contents_known")):
            return error(
                "carried_work_already_known",
                f"deployment run {resolved_run_id!r} already carries a derived "
                "record; repair replaces only a comparison that never ran",
                jsonpath="$.target.workflow_run_id",
            )
        repaired = derive_carried_work_safely(conn, resolved_run_id)
        fresh = _derivation(repaired)
        if not bool(fresh.get("contents_known")):
            return error(
                "carried_work_still_unknown",
                f"deployment run {resolved_run_id!r} still cannot be compared: "
                f"{fresh.get('reason') or 'unknown'}. "
                f"{fresh.get('recovery') or ''}".strip(),
                jsonpath="$.target.workflow_run_id",
            )
        conn.execute(
            f"UPDATE deployment_runs SET {CARRIED_WORK_FIELD}=%s WHERE id=%s",
            (dumps_compact(repaired), resolved_run_id),
        )
        conn.commit()
        return HandlerOutcome(
            result_payload={
                "run_id": resolved_run_id,
                "repaired": True,
                "previous_reason": str(previous.get("reason") or ""),
                "carried_work": repaired,
            },
            primary_success=True,
        )
    finally:
        conn.close()


__all__ = [
    "DeploymentRunCarriedWorkRepairRequest",
    "DeploymentRunCarriedWorkRepairResponse",
    "handle_deployment_run_carried_work_repair",
]
