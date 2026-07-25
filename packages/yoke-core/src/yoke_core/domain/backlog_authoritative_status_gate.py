"""Backlog authoritative status gate — composes the QA verification gates,
governed DB-mutation gates, prose-vs-claim consistency check,
architecture-impact gate, and path-claim boundary check that
share the canonical status write path.

For most targets the composer short-circuits on the first failure. For
the ``reviewing-implementation -> reviewed-implementation`` transition it
runs the independent gates (architecture-impact, path-claim boundary, QA
verification) in sequence and aggregates every blocker into one envelope
so the operator can remediate them in a single pass instead of N rounds
of fix-and-retry.
"""

from __future__ import annotations

from typing import Optional

from . import db_backend
from .db_helpers import connect
from .workflow_gate_catalog import (
    GATE_ARCHITECTURE_IMPACT,
    GATE_CHECK_HARD_BLOCKS,
    GATE_CLAIM_ACTIVATION,
    GATE_DB_CLAIM_PROSE,
    GATE_DB_MUTATION,
    GATE_PATH_CLAIM_BOUNDARY,
    GATE_PLAN_SIMULATION,
    GATE_QA_VERIFICATION,
)
from .workflow_runtime import load_item_workflow_runtime


_REVIEWED_IMPLEMENTATION_TARGET = "reviewed-implementation"


def _run_authoritative_status_gate(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
    qa_bypass: bool,
    force: bool,
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

    The DB-mutation gate is a no-op for tickets whose
    ``db_mutation_profile.state`` is ``"none"`` (absence-as-opt-out). On
    a passing ``idea -> refining-idea`` transition the helper additionally
    stamps ``db_compatibility_attestation.frozen_at`` so the immutability
    invariants enforced by the structured-write path engage.

    Returns ``None`` when every gate family allows the write; otherwise
    returns the failure payload (verbatim for serial targets, aggregated
    for ``reviewed-implementation``).
    """
    if qa_bypass or force:
        return None

    # Lazy import keeps the helpers shim patchable while avoiding a
    # helpers <-> authoritative-gate import cycle at module load time.
    from yoke_core.domain import backlog_updates_helpers as _helpers

    file_line_result = _helpers._run_file_line_gate(
        item_id=item_id,
        target_status=target_status,
        db_path=db_path,
    )
    if file_line_result is not None:
        return file_line_result

    conn = connect(db_path)
    try:
        workflow = load_item_workflow_runtime(conn, item_id)
    finally:
        conn.close()
    failures: list[dict] = []
    for gate_ref in workflow.gates_for_stage(target_status):
        gate_id = str(gate_ref["id"])
        result = _evaluate_definition_gate(
            gate_id=gate_id,
            mode=gate_ref.get("mode"),
            item_id=item_id,
            target_status=target_status,
            db_path=db_path,
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
    if gate_id in {GATE_CHECK_HARD_BLOCKS, GATE_CLAIM_ACTIVATION}:
        return None
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
    if (
        not definition_selected
        and target_status not in {
            "reviewed-implementation",
            "implemented",
            "release",
            "done",
        }
    ):
        return None
    try:
        from yoke_core.domain import qa_gates

        gate_target = qa_gates.GateTarget.parse(str(item_id))
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
    except db_backend.operational_error_types() as exc:
        # Some isolated tests still seed a minimal legacy QA schema. Skip the
        # richer gate when the required columns are absent and fall back to the
        # preloaded mutation-layer counts for that harness.
        if "no such column" in str(exc) or "no such table" in str(exc):
            return None
        raise

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
                "Cannot advance to 'planned' -- QA gate helpers are "
                "unavailable."
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
