"""Compose one stage's live gate list from its definition plus policy.

``policies.path_survey`` published an obligation nothing read: the
effective-policy projection resolved ``requires_path_survey`` and no
runtime consumer ever asked, so a definition publishing ``optional`` still
carried ``conflict_survey`` on its implementing stage and still refused a
transition without a recorded survey. A policy that cannot move the gate
list is decoration, and an item whose workflow says the survey is optional
was being told otherwise by the write path.

A policy-gated gate is therefore selected out of the stage list before the
composer evaluates anything: the pinned definition still names every gate
the workflow may enforce, and the policy decides which of them this item
actually owes.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.workflow_gate_catalog import GATE_CONFLICT_SURVEY

#: Gate id -> the effective-policy predicate that decides whether the stage
#: really carries it. Read the projection, never the raw pinned policy.
_POLICY_GATED_GATES = {GATE_CONFLICT_SURVEY: "requires_path_survey"}


def select_stage_gates(
    gate_refs: tuple[Mapping[str, Any], ...],
    *,
    item_id: int,
    db_path: str,
    conn: Optional[Any] = None,
) -> tuple[Mapping[str, Any], ...]:
    """Drop the gates this item's effective policy turned off."""
    if not any(str(ref["id"]) in _POLICY_GATED_GATES for ref in gate_refs):
        return gate_refs
    from yoke_core.domain.workflow_effective_policies import (
        load_item_effective_workflow_policies,
    )

    policy_conn = conn if conn is not None else connect(db_path)
    try:
        policies = load_item_effective_workflow_policies(
            policy_conn, int(item_id)
        )
    finally:
        if conn is None:
            policy_conn.close()
    return tuple(ref for ref in gate_refs if _gate_applies(ref, policies))


def _gate_applies(ref: Mapping[str, Any], policies: Any) -> bool:
    """Whether this item's effective policy still owes this gate."""
    predicate = _POLICY_GATED_GATES.get(str(ref["id"]))
    return True if predicate is None else bool(getattr(policies, predicate))


__all__ = ["select_stage_gates"]
