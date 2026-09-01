"""Live status-write evaluation of the two activation-operation gates.

The delivery workflows list ``check_hard_blocks`` and ``claim_activation``
on their implementing stage. Both returned ``None`` unconditionally on the
status write, so every reader of the definition believed a transition into
implementing was gated on upstream dependencies and on the item's path
claims having taken their door lock, while nothing was checked. A gate a
definition lists and the write path ignores is a lie about what happened,
which is worse than an honest absence.

They run here instead, on the same connection the transition is about to
commit through:

* ``check_hard_blocks`` — every ``item_dependencies`` blocker gated at
  activation must satisfy its own condition, the identical evaluation the
  advance preflight and the frontier already share.
* ``claim_activation`` — no path claim the item owns may still be sitting
  in ``planned`` or ``blocked``. Registration alone is not activation: a
  planned claim holds no door lock, and a blocked one names a live
  conflicting holder.

Where a check genuinely cannot apply — a fixture universe with no dependency
or path-claim registry — the gate records ``WorkflowGateAbsent`` rather than
passing quietly.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_gate_absence import record_gate_absence
from yoke_core.domain.workflow_gate_catalog import (
    GATE_CHECK_HARD_BLOCKS,
    GATE_CLAIM_ACTIVATION,
)

#: Dependency rows carrying this gate point block entry into implementing.
#: Integration- and closure-gated rows are answered at their own boundary.
ACTIVATION_GATE_POINT = "activation"

_GATE_IDS = frozenset({GATE_CHECK_HARD_BLOCKS, GATE_CLAIM_ACTIVATION})


def handles(gate_id: str) -> bool:
    return gate_id in _GATE_IDS


def _blocker_summary(line: str) -> str:
    """Render one ``BLOCKED|ref|status|title|gate|satisfaction`` row."""
    parts = line.split("|")
    if len(parts) < 6:
        return line
    _, ref, status, title, _gate, satisfaction = parts[:6]
    return f"{ref} ({status}) {title!r} — needs {satisfaction}"


def evaluate_check_hard_blocks(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
    session_id: Optional[str] = None,
    conn: Optional[Any] = None,
) -> Optional[dict]:
    """Refuse while an activation-gated upstream dependency is unsatisfied."""
    from yoke_core.domain.check_hard_blocks import evaluate_blockers

    gate_conn = conn if conn is not None else connect(db_path)
    try:
        registry_present = _table_exists(gate_conn, "item_dependencies")
        blocked = (
            evaluate_blockers(
                int(item_id),
                gate_filter=ACTIVATION_GATE_POINT,
                conn=gate_conn,
            )
            if registry_present
            else []
        )
    finally:
        if conn is None:
            gate_conn.close()
    if not registry_present:
        record_gate_absence(
            gate_id=GATE_CHECK_HARD_BLOCKS,
            item_id=int(item_id),
            target_status=target_status,
            reason="dependency_registry_absent",
            detail="this universe has no item_dependencies registry to evaluate",
            conn=conn,
        )
        return None
    if not blocked:
        return None
    summary = "; ".join(_blocker_summary(line) for line in blocked)
    return {
        "success": False,
        "error_code": "GATE_HARD_BLOCKS_UNSATISFIED",
        "error": (
            f"Cannot advance to {target_status!r} — "
            f"{len(blocked)} upstream dependency(ies) gated at activation "
            f"remain unsatisfied: {summary}."
        ),
        "remediation_hint": (
            "Land the blocking item, or amend the dependency with "
            "`yoke items dependency list <item>` evidence when the edge "
            "is no longer real."
        ),
    }


def evaluate_claim_activation(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
    session_id: Optional[str] = None,
    conn: Optional[Any] = None,
) -> Optional[dict]:
    """Refuse while a registered path claim has not taken its door lock."""
    from yoke_core.domain.path_claims_gate import gate_state_for_item

    gate_conn = conn if conn is not None else connect(db_path)
    try:
        pending = gate_state_for_item(gate_conn, int(item_id))
    finally:
        if conn is None:
            gate_conn.close()
    if pending is None:
        record_gate_absence(
            gate_id=GATE_CLAIM_ACTIVATION,
            item_id=int(item_id),
            target_status=target_status,
            reason="path_claim_registry_absent",
            detail="this universe has no path_claims registry to activate",
            conn=conn,
        )
        return None
    if not pending:
        return None
    summary = ", ".join(f"id={cid} state={state}" for cid, state in pending)
    return {
        "success": False,
        "error_code": "GATE_CLAIM_ACTIVATION_UNSATISFIED",
        "error": (
            f"Cannot advance to {target_status!r} — path claim(s) registered "
            f"for this item never took the door lock: {summary}. A 'blocked' "
            "claim names a live conflicting holder; a 'planned' one was "
            "registered but never activated."
        ),
        "remediation_hint": (
            "Prepare the item worktree, which activates the registered "
            "claims, or coordinate with the holder a blocked claim names."
        ),
    }


def evaluate(
    *,
    gate_id: str,
    item_id: int,
    target_status: str,
    db_path: str,
    session_id: Optional[str] = None,
    conn: Optional[Any] = None,
) -> Optional[dict]:
    """Run one activation gate; callers must check :func:`handles` first."""
    evaluator = (
        evaluate_check_hard_blocks
        if gate_id == GATE_CHECK_HARD_BLOCKS
        else evaluate_claim_activation
    )
    return evaluator(
        item_id=item_id,
        target_status=target_status,
        db_path=db_path,
        session_id=session_id,
        conn=conn,
    )


__all__ = [
    "ACTIVATION_GATE_POINT",
    "evaluate",
    "evaluate_check_hard_blocks",
    "evaluate_claim_activation",
    "handles",
]
