"""Record a listed workflow gate that did not apply, and why.

A gate a definition lists but that cannot apply to this project — no
approving authority is declared, the obligation belongs to a rung this
project has not reached — is legitimately absent. What is never legitimate
is that absence being invisible: a reader of the definition believes the
gate ran. Every such skip lands here as one ``WorkflowGateAbsent`` audit
row naming the gate, the transition, and the missing declaration, so a
skip is countable without turning it into a refusal.
"""

from __future__ import annotations

from typing import Any, Optional

WORKFLOW_GATE_ABSENT_EVENT_NAME = "WorkflowGateAbsent"


def record_gate_absence(
    *,
    gate_id: str,
    item_id: int,
    target_status: str,
    reason: str,
    detail: str = "",
    conn: Optional[Any] = None,
) -> None:
    """Emit the audit row for one listed-but-inapplicable gate.

    Telemetry never gates a transition, so a failed write degrades to a
    print rather than raising into the caller's status path.
    """
    from yoke_core.domain.events import emit_event

    try:
        emit_event(
            WORKFLOW_GATE_ABSENT_EVENT_NAME,
            event_kind="audit",
            event_type="workflow_gate_absence",
            source_type="system",
            severity="WARN",
            outcome="skipped",
            item_id=str(int(item_id)),
            context={
                "gate_id": gate_id,
                "target_status": target_status,
                "reason": reason,
                "detail": detail,
            },
            conn=conn,
        )
    except Exception as exc:  # noqa: BLE001 - telemetry never gates a write
        print(
            f"Warning: {WORKFLOW_GATE_ABSENT_EVENT_NAME} not recorded for "
            f"gate {gate_id!r} at {target_status!r}: {exc}"
        )


__all__ = [
    "WORKFLOW_GATE_ABSENT_EVENT_NAME",
    "record_gate_absence",
]
