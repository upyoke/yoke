"""Compose the gates that share the authoritative backlog status write path.

Most targets short-circuit on the first failure. The
``reviewing-implementation -> reviewed-implementation`` transition aggregates
its independent blockers so the operator can remediate them in one pass.
"""

from __future__ import annotations

from typing import Any, Optional

from .db_helpers import connect
from .qa_terminal_settlement import terminal_transition_result
from .workflow_gate_catalog import (
    GATE_ARCHITECTURE_IMPACT,
    GATE_CONFLICT_SURVEY,
    GATE_DB_CLAIM_PROSE,
    GATE_DB_MUTATION,
    GATE_DOC_CLAIM_ACTIVATION,
    GATE_PATH_CLAIM_BOUNDARY,
    GATE_PLAN_SIMULATION,
    GATE_QA_VERIFICATION,
    GATE_WORK_CLAIM_ACTIVATION,
)
from .workflow_runtime import load_item_workflow_runtime
from .workflow_stage_gate_selection import select_stage_gates


_REVIEWED_IMPLEMENTATION_TARGET = "reviewed-implementation"
_ACTIVATION_GATE_IDS = frozenset(
    {
        GATE_WORK_CLAIM_ACTIVATION,
        GATE_DOC_CLAIM_ACTIVATION,
    }
)
_NON_BYPASSABLE_ACTIVATION_GATE_IDS = _ACTIVATION_GATE_IDS | {GATE_CONFLICT_SURVEY}


def _run_authoritative_status_gate(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
    qa_bypass: bool,
    force: bool,
    session_id: Optional[str] = None,
    conn: Optional[Any] = None,
) -> Optional[dict]:
    """Run the authoritative QA + governed-DB-mutation gates for status writes.

    Composes the gate families that share the canonical write path:
    * Governed DB-mutation gate (governed DB-mutation contract) for ``refining-idea``,
      ``reviewing-implementation``, ``implemented`` plus the prose check
      for ``refining-idea``, ``refined-idea``, ``planned``,
      ``reviewing-implementation``, ``implemented``.
    * Architecture-impact gate for every transition that has impact.
    * Path-claim boundary check (worktree-bound transitions).
    * Plan-simulation gate at ``planned``.
    * QA verification / done gate for ``reviewed-implementation``,
      ``implemented``, ``release``, ``done``.
    The DB-mutation gate is a no-op for work items whose
    ``db_mutation_profile.state`` is ``"none"`` (absence-as-opt-out). On
    a passing ``idea -> refining-idea`` transition the helper additionally
    stamps ``db_compatibility_attestation.frozen_at`` so the immutability
    invariants enforced by the structured-write path engage.

    Returns ``None`` when every gate family allows the write; otherwise
    returns the failure payload (verbatim for serial targets, aggregated
    for ``reviewed-implementation``).
    """
    if qa_bypass:
        from yoke_core.domain.qa_gate_preconditions import (
            QA_BYPASS_FORBIDDEN,
            qa_bypass_result,
        )

        bypass = qa_bypass_result(requested=True)
        if bypass is not None and not bypass.passed:
            return {
                "success": False,
                "error_code": QA_BYPASS_FORBIDDEN,
                "error": "\n".join(bypass.errors),
            }
    bypass_non_activation = qa_bypass or force

    if conn is None:
        workflow_conn = connect(db_path)
        try:
            workflow = load_item_workflow_runtime(workflow_conn, item_id)
        finally:
            workflow_conn.close()
    else:
        workflow = load_item_workflow_runtime(conn, item_id)
    terminal_gate = terminal_transition_result(conn, item_id, target_status, workflow)
    if terminal_gate:
        return terminal_gate
    if workflow.workflow_id == "dash":
        from yoke_core.domain.dash_posture_gate import evaluate as evaluate_posture

        posture_result = evaluate_posture(
            item_id=item_id,
            target_status=target_status,
            db_path=db_path,
        )
        if posture_result is not None:
            return posture_result
    failures: list[dict] = []
    gate_refs = select_stage_gates(
        workflow.gates_for_stage(target_status),
        item_id=item_id,
        db_path=db_path,
        conn=conn,
    )
    if bypass_non_activation:
        gate_refs = tuple(
            ref
            for ref in gate_refs
            if str(ref["id"]) in _NON_BYPASSABLE_ACTIVATION_GATE_IDS
        )
        if not gate_refs:
            return None
    ordered_refs = sorted(
        gate_refs,
        key=lambda ref: str(ref["id"]) in _ACTIVATION_GATE_IDS,
    )
    for gate_ref in ordered_refs:
        gate_id = str(gate_ref["id"])
        result = _evaluate_definition_gate(
            gate_id=gate_id,
            mode=gate_ref.get("mode"),
            item_id=item_id,
            target_status=target_status,
            db_path=db_path,
            session_id=session_id,
            conn=conn,
        )
        if result is None:
            continue
        if target_status != _REVIEWED_IMPLEMENTATION_TARGET:
            return result
        failures.append(_failure_entry(gate_id, result))
    if not failures:
        return None
    first = failures[0]
    return {
        "success": False,
        "transitioned": False,
        "error_code": first["error_code"],
        "error": first["error_message"],
        "failures": failures,
    }


def _evaluate_definition_gate(
    *,
    gate_id: str,
    mode: Optional[str],
    item_id: int,
    target_status: str,
    db_path: str,
    session_id: Optional[str] = None,
    conn: Optional[Any] = None,
) -> Optional[dict]:
    """Dispatch one definition-owned gate reference to registered code."""
    from yoke_core.domain import backlog_updates_helpers as _helpers

    if gate_id == GATE_DB_CLAIM_PROSE:
        return _helpers._run_prose_vs_claim_check(
            item_id=item_id,
            db_path=db_path,
        )
    if gate_id == GATE_DB_MUTATION:
        return _helpers._run_db_mutation_gate(
            item_id=item_id,
            target_status=target_status,
            db_path=db_path,
            gate_kind_override=str(mode or ""),
            include_prose=False,
            conn=conn,
        )
    if gate_id == GATE_ARCHITECTURE_IMPACT:
        from yoke_core.domain.backlog_architecture_gate_runner import (
            _run_architecture_impact_gate,
        )

        return _run_architecture_impact_gate(
            item_id=item_id,
            target_status=target_status,
            db_path=db_path,
            definition_selected=True,
        )
    if gate_id == GATE_PATH_CLAIM_BOUNDARY:
        return _evaluate_path_claim_boundary(
            item_id=item_id,
            target_status=target_status,
            db_path=db_path,
            definition_selected=True,
        )
    if gate_id == GATE_PLAN_SIMULATION:
        return _evaluate_plan_simulation(item_id=item_id, db_path=db_path)
    if gate_id == GATE_QA_VERIFICATION:
        return _evaluate_qa_verification(
            item_id=item_id,
            target_status=target_status,
            db_path=db_path,
            definition_selected=True,
        )
    from yoke_core.domain import workflow_gate_family_dispatch

    if workflow_gate_family_dispatch.handles(gate_id):
        return workflow_gate_family_dispatch.evaluate(
            gate_id=gate_id,
            item_id=item_id,
            target_status=target_status,
            db_path=db_path,
            session_id=session_id,
            conn=conn,
        )
    return {
        "success": False,
        "error_code": "GATE_IMPLEMENTATION_UNAVAILABLE",
        "error": (
            f"Workflow gate {gate_id!r} is registered but has no live "
            "status-transition implementation."
        ),
    }


_QA_VERIFICATION_ERROR_CODES = {
    "reviewed-implementation": "GATE_QA_REVIEWED_IMPLEMENTATION",
    "implemented": "GATE_QA_IMPLEMENTED",
    "release": "GATE_QA_RELEASE",
}


def _evaluate_qa_verification(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
    definition_selected: bool = False,
) -> Optional[dict]:
    """Run the QA verification or done gate for late-stage transitions.

    Returns the canonical failure payload, or ``None`` when the gate is
    satisfied or unavailable for this target.
    """
    if not definition_selected and target_status not in {
        "reviewed-implementation",
        "implemented",
        "release",
        "done",
    }:
        return None
    from yoke_core.domain import qa_gates

    gate_target = qa_gates.GateTarget(item_id=int(item_id))
    if target_status == "done":
        gate_result = qa_gates.check_done_gate(gate_target, db_path)
        error_code = "GATE_QA_DONE"
    else:
        gate_result = qa_gates.check_verification_gate(
            gate_target,
            db_path,
            transition_name=target_status,
        )
        error_code = _QA_VERIFICATION_ERROR_CODES[target_status]

    if gate_result.passed:
        return None

    return {
        "success": False,
        "error": "\n".join(gate_result.errors) or "Authoritative QA gate failed",
        "error_code": error_code,
    }


def _evaluate_path_claim_boundary(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
    definition_selected: bool = False,
) -> Optional[dict]:
    """Run the path-claim boundary check when the helper is importable."""
    try:
        from yoke_core.domain import path_claims_gate_boundary
    except ImportError:
        return None
    return path_claims_gate_boundary.check_boundary_for_item(
        item_id=item_id,
        target_status=target_status,
        db_path=db_path,
        definition_selected=definition_selected,
    )


def _evaluate_plan_simulation(
    *,
    item_id: int,
    db_path: str,
) -> Optional[dict]:
    """Run the plan-simulation gate at ``planned``."""
    try:
        from yoke_core.domain import qa_gates
    except ImportError:
        return {
            "success": False,
            "error_code": "GATE_PLAN_SIM_UNAVAILABLE",
            "error": (
                "Cannot advance to 'planned' -- QA gate helpers are unavailable."
            ),
        }

    plan_result = qa_gates.check_plan_simulation_satisfied(item_id, db_path)
    if plan_result.passed:
        return None
    return {
        "success": False,
        "error_code": "GATE_PLAN_SIM_UNSATISFIED",
        "error": "\n".join(plan_result.errors),
    }


def _failure_entry(gate_id: str, payload: dict) -> dict:
    """Normalize a serial gate-failure payload into an aggregator entry."""
    return {
        "gate_id": gate_id,
        "error_code": payload.get("error_code") or "GATE_UNKNOWN",
        "error_message": payload.get("error") or "",
        "remediation_hint": payload.get("remediation_hint") or "",
    }


__all__ = ["_run_authoritative_status_gate"]
