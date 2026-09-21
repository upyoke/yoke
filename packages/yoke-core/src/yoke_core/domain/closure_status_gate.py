"""Refuse a done status write while a closure-gated dependency is unsatisfied.

Activation is listed on implementing and integration is composed at
deployment. Closure's declared meaning is completion, so every
authoritative write to ``done`` evaluates ``evaluate_blockers`` at
``gate_filter=closure`` — the same evaluator the other gates already
share. An unreadable evaluation refuses; an empty result lets the write
continue. This is not a listed workflow gate and is not skippable by
``force`` or QA bypass.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.dependency_explanation import explain_dependency
from yoke_core.domain.dependency_types import GatePoint
from yoke_core.domain.schema_common import _table_exists

_DONE = "done"
_ERROR_CODE = "GATE_CLOSURE_UNSATISFIED"


def evaluate_for_status_write(
    *,
    item_id: int,
    target_status: str,
    db_path: str = "",
    conn: Optional[Any] = None,
) -> Optional[dict]:
    """Run on the authoritative status-write composer; no-op off ``done``."""
    if target_status != _DONE:
        return None
    return evaluate(item_id=item_id, db_path=db_path, conn=conn)


def evaluate(
    *,
    item_id: int,
    db_path: str = "",
    conn: Optional[Any] = None,
) -> Optional[dict]:
    """Return a composer failure payload, or ``None`` when closure is clear."""
    from yoke_core.domain.check_hard_blocks import evaluate_blockers
    from yoke_core.domain.db_helpers import connect

    owned = conn is None
    gate_conn = connect(db_path) if owned else conn
    try:
        if not _table_exists(gate_conn, "item_dependencies"):
            return None
        blockers = evaluate_blockers(
            int(item_id),
            gate_filter=GatePoint.CLOSURE.value,
            conn=gate_conn,
        )
    except Exception as exc:  # noqa: BLE001 - refuse; never degrade open
        return {
            "success": False,
            "error_code": _ERROR_CODE,
            "error": (
                "Cannot complete this item — closure dependencies could "
                f"not be evaluated ({exc}). Restore the control-plane "
                "read and retry."
            ),
        }
    finally:
        if owned:
            gate_conn.close()
    if not blockers:
        return None
    summaries = "; ".join(_summarize(line) for line in blockers)
    return {
        "success": False,
        "error_code": _ERROR_CODE,
        "error": (
            f"Cannot complete this item — {len(blockers)} closure "
            f"dependency(ies) remain unsatisfied: {summaries}."
        ),
        "remediation_hint": (
            "The wait discharges when the blocker meets its recorded "
            "satisfaction condition; do not set items.blocked for a wait "
            "another item already carries."
        ),
    }


def _summarize(line: str) -> str:
    """Render one BLOCKED line as blocker + condition + discharge reason."""
    parts = line.split("|")
    if len(parts) < 6:
        return line
    _, ref, status, _title, gate, satisfaction = parts[:6]
    reason = parts[6] if len(parts) > 6 else ""
    text = explain_dependency(gate, satisfaction, ref, status)
    return f"{text}: {reason}" if reason else text


__all__ = ["evaluate", "evaluate_for_status_write"]
