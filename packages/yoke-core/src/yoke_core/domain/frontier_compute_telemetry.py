"""FrontierComputed telemetry emission for the frontier computation."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .frontier_types import AdapterCategory, FrontierResult

_logger = logging.getLogger(__name__)


def _emit_frontier_computed(
    conn: Any,
    result: FrontierResult,
    project_scope: List[int],
    wip_cap: int,
    wip_active: int,
    t0: float,
    *,
    session_id: Optional[str] = None,
    excluded_routed_ownership: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Emit a FrontierComputed event with core-owned frontier context.

    Telemetry item identity is the bare internal ``items.id`` integer.
    """
    try:
        from .events import emit_event
        from .frontier_compute import (
            _canonical_project_label,
            _project_scope_labels,
        )

        duration_ms = int((time.monotonic() - t0) * 1000)
        ranking_summary = [
            {
                "item_id": fi.item_id,
                "priority": fi.priority,
                "adapter": fi.adapter.value
                if isinstance(fi.adapter, AdapterCategory)
                else str(fi.adapter),
            }
            for fi in result.runnable[:5]
        ]

        excluded_details = list(excluded_routed_ownership or [])
        emit_event(
            "FrontierComputed",
            event_kind="workflow",
            event_type="frontier_computation",
            source_type="backend",
            session_id=session_id or "",
            duration_ms=duration_ms,
            project=_canonical_project_label(conn, project_scope),
            context={
                "project_scope": _project_scope_labels(conn, project_scope),
                "wip_cap": wip_cap,
                "wip_active": wip_active,
                "runnable_count": len(result.runnable),
                "blocked_count": len(result.blocked),
                "frozen_count": len(result.frozen),
                "conduct_eligible_count": len(result.conduct_eligible),
                "ranking_summary": ranking_summary,
                "duration_ms": duration_ms,
                "excluded_routed_ownership_count": len(excluded_details),
                "excluded_routed_ownership": excluded_details,
            },
        )
    except Exception as exc:
        _logger.debug("FrontierComputed emission failed: %s", exc)


__all__ = ["_emit_frontier_computed"]
