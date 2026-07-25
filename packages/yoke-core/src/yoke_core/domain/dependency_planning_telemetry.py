"""Telemetry emitted by dependency gate planning."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .dependency_planning_results import BlockerDetail

_logger = logging.getLogger(__name__)


def emit_batch_gate_evaluated(
    gate_point: str,
    total_rows: int,
    blocks: Dict[str, List[BlockerDetail]],
    *,
    session_id: Optional[str] = None,
    project: Optional[str] = None,
) -> None:
    """Emit a batch summary event for dependency gate evaluation."""
    try:
        from .events import emit_event

        unsatisfied_summary = [
            {
                "item_id": dependent,
                "blocking_item": detail.blocking_item,
                "gate_point": detail.gate_point,
                "satisfaction": detail.satisfaction,
                "reason": detail.reason,
                "rationale": detail.rationale,
            }
            for dependent, details in blocks.items()
            for detail in details
        ]
        emit_event(
            "DependencyGateEvaluated",
            event_kind="workflow",
            event_type="dependency_gate",
            source_type="backend",
            session_id=session_id or "",
            project=project or "yoke",
            context={
                "gate_point": gate_point,
                "total_rows_evaluated": total_rows,
                "unsatisfied_count": len(unsatisfied_summary),
                "blocked_item_count": len(blocks),
                "unsatisfied_summary": unsatisfied_summary[:20],
            },
        )
    except Exception as exc:
        _logger.debug("DependencyGateEvaluated emission failed: %s", exc)


__all__ = ["emit_batch_gate_evaluated"]
