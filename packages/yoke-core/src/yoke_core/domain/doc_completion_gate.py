"""Closure gate for document-led Blitz execution."""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.strategy_coordination import blitz_completion_evidence


def evaluate(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
) -> Optional[dict]:
    """Require the linked document's completion and reconciliation record."""
    conn = connect(db_path)
    try:
        evidence = blitz_completion_evidence(conn, item_id)
    finally:
        conn.close()
    if evidence["satisfied"]:
        return None
    missing = ", ".join(str(value) for value in evidence.get("missing") or [])
    return {
        "success": False,
        "error_code": "GATE_DOC_COMPLETION_UNSATISFIED",
        "error": (
            "The Blitz execution document is not ready to close; missing: "
            f"{missing or 'completion evidence'}."
        ),
        "remediation_hint": (
            "Record what completed, what changed, what remains, verification "
            "evidence, and parent reconciliation in the linked document."
        ),
    }


__all__ = ["evaluate"]
