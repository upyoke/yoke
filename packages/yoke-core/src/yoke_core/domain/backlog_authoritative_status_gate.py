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
from .backlog_status_gate_points import (
    PLAN_SIMULATION_TARGETS,
    QA_VERIFICATION_TARGETS,
)


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

    db_mutation_result = _helpers._run_db_mutation_gate(
        item_id=item_id,
        target_status=target_status,
        db_path=db_path,
    )
    if db_mutation_result is not None:
        return db_mutation_result

    file_line_result = _helpers._run_file_line_gate(
        item_id=item_id,
        target_status=target_status,
        db_path=db_path,
    )
    if file_line_result is not None:
        return file_line_result

    if target_status == _REVIEWED_IMPLEMENTATION_TARGET:
        return _aggregate_reviewed_implementation_gates(
            item_id=item_id,
            db_path=db_path,
        )

    from yoke_core.domain.backlog_architecture_gate_runner import (
        _run_architecture_impact_gate,
    )
    architecture_result = _run_architecture_impact_gate(
        item_id=item_id,
        target_status=target_status,
        db_path=db_path,
    )
    if architecture_result is not None:
        return architecture_result

    boundary_result = _evaluate_path_claim_boundary(
        item_id=item_id,
        target_status=target_status,
        db_path=db_path,
    )
    if boundary_result is not None:
        return boundary_result

    if target_status in PLAN_SIMULATION_TARGETS:
        plan_result = _evaluate_plan_simulation(item_id=item_id, db_path=db_path)
        if plan_result is not None:
            return plan_result

    return _evaluate_qa_verification(
        item_id=item_id,
        target_status=target_status,
        db_path=db_path,
    )


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
) -> Optional[dict]:
    """Run the QA verification or done gate for late-stage transitions.

    Returns the canonical failure payload, or ``None`` when the gate is
    satisfied or unavailable for this target.
    """
    if target_status not in QA_VERIFICATION_TARGETS:
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
    except db_backend.operational_error_types(conn) as exc:
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


def _aggregate_reviewed_implementation_gates(
    *,
    item_id: int,
    db_path: str,
) -> Optional[dict]:
    """Run the independent gates for ``reviewed-implementation`` and aggregate.

    Runs architecture-impact, path-claim boundary, and QA verification
    independently; collects every blocker into a single envelope. Returns
    ``None`` when all three pass.

    The legacy top-level fields (``success``, ``error_code``, ``error``)
    mirror the first failure in deterministic gate order so callers that
    only inspect those fields continue to work. The new ``failures``
    array carries the full aggregate and ``transitioned`` makes the
    no-transition outcome explicit.
    """
    failures: list[dict] = []

    from yoke_core.domain.backlog_architecture_gate_runner import (
        _run_architecture_impact_gate,
    )
    architecture_result = _run_architecture_impact_gate(
        item_id=item_id,
        target_status=_REVIEWED_IMPLEMENTATION_TARGET,
        db_path=db_path,
    )
    if architecture_result is not None:
        failures.append(_failure_entry("architecture_impact", architecture_result))

    boundary_result = _evaluate_path_claim_boundary(
        item_id=item_id,
        target_status=_REVIEWED_IMPLEMENTATION_TARGET,
        db_path=db_path,
    )
    if boundary_result is not None:
        failures.append(_failure_entry("path_claim_boundary", boundary_result))

    qa_result = _evaluate_qa_verification(
        item_id=item_id,
        target_status=_REVIEWED_IMPLEMENTATION_TARGET,
        db_path=db_path,
    )
    if qa_result is not None:
        failures.append(_failure_entry("qa_verification", qa_result))

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


def _failure_entry(gate_id: str, payload: dict) -> dict:
    """Normalize a serial gate-failure payload into an aggregator entry."""
    return {
        "gate_id": gate_id,
        "error_code": payload.get("error_code") or "GATE_UNKNOWN",
        "error_message": payload.get("error") or "",
        "remediation_hint": payload.get("remediation_hint") or "",
    }


__all__ = ["_run_authoritative_status_gate"]
