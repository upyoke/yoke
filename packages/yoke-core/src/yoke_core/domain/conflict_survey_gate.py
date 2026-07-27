"""Status-gate evaluator for a recorded direct-workflow conflict survey."""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.conflict_survey import (
    read_recorded_survey,
    survey_conflicts,
)
from yoke_core.domain.db_helpers import connect


def evaluate(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
) -> Optional[dict]:
    """Re-run the saved touch set against live coordination state."""
    conn = connect(db_path)
    try:
        recorded = read_recorded_survey(conn, item_id)
        if not recorded:
            return {
                "success": False,
                "error_code": "GATE_CONFLICT_SURVEY_MISSING",
                "error": (
                    "Record a conflict survey with the inferred touch set "
                    "before entering implementation."
                ),
            }
        try:
            result = survey_conflicts(
                conn,
                item_id=item_id,
                touch_paths=recorded.get("touch_paths") or (),
                integration_target=str(
                    recorded.get("integration_target") or "main"
                ),
            )
        except (LookupError, ValueError) as exc:
            return {
                "success": False,
                "error_code": "GATE_CONFLICT_SURVEY_INVALID",
                "error": str(exc),
            }
    finally:
        conn.close()
    if result.clear:
        return None
    details = "; ".join(
        f"{row.kind} item={row.owner_item_id or '-'} path={row.path} "
        f"({row.detail})"
        for row in result.blockers
    )
    return {
        "success": False,
        "error_code": "GATE_CONFLICT_SURVEY_BLOCKED",
        "error": (
            "Registered coordination wins over claim-less work: " + details
        ),
        "remediation_hint": (
            "Coordinate or wait, narrow the touch set, register path claims, "
            "or escalate the work item."
        ),
    }


__all__ = ["evaluate"]
