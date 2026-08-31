"""Closure gate for Dash result and verification evidence."""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.dash_execution import evaluate_dash_evidence
from yoke_core.domain.db_helpers import connect


def evaluate(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
) -> Optional[dict]:
    """Require the canonical Dash execution-evidence record."""
    conn = connect(db_path)
    try:
        verdict = evaluate_dash_evidence(conn, item_id)
    except (LookupError, ValueError) as exc:
        return {
            "success": False,
            "error_code": "GATE_DASH_EVIDENCE_INVALID",
            "error": str(exc),
        }
    finally:
        conn.close()
    if verdict.satisfied:
        return None
    return {
        "success": False,
        "error_code": "GATE_DASH_EVIDENCE_UNSATISFIED",
        "error": (
            "Dash execution evidence is incomplete; missing: "
            + ", ".join(verdict.missing)
        ),
        "remediation_hint": (
            "Record the result, passing verification, and either commit and "
            "merge SHAs or an agent-attested floor (no-changes / task "
            "close-out), plus touched files and every tightened posture check."
        ),
    }


__all__ = ["evaluate"]
