"""Closure gate for the floor attestation on task done."""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.dash_execution import evaluate_dash_evidence
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.floor_attestation import outward_action_approval_seam

_REMEDIATION = (
    "Record the agent account and observed changes through direct-workflow "
    "evidence; that surface stamps the agent_attested done obligation in "
    "item_gate_satisfactions. Merge SHAs are not required."
)


def evaluate(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
) -> Optional[dict]:
    """Require the floor attestation; SHAs are not the satisfier."""
    blocked = outward_action_approval_seam()
    if blocked is not None:
        return blocked
    conn = connect(db_path)
    try:
        verdict = evaluate_dash_evidence(conn, item_id)
    except (LookupError, ValueError) as exc:
        return {
            "success": False,
            "error_code": "GATE_FLOOR_ATTESTATION_INVALID",
            "error": str(exc),
        }
    finally:
        conn.close()
    missing = list(verdict.missing)
    if not missing:
        return None
    return {
        "success": False,
        "error_code": "GATE_FLOOR_ATTESTATION_UNSATISFIED",
        "error": ("Floor attestation is incomplete; missing: " + ", ".join(missing)),
        "remediation_hint": _REMEDIATION,
    }


__all__ = ["evaluate"]
