"""Shared session-holdings grouping for board and roster renderers.

Readers contribute display-shaped observations in their intended display order. This
module owns the semantics that both session surfaces must share: current wins
over previous, one row per target, and a caller-supplied previous-row budget.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


SESSION_PATH_HOLDING_KEY = "path:session"


def work_holding_key(
    target_kind: str,
    *,
    item_id: Any = None,
    epic_id: Any = None,
    task_num: Any = None,
    process_key: Any = None,
    project_id: Any = None,
    rendered_target: str = "",
) -> str:
    """Return the canonical identity for one work-claim target."""
    kind = str(target_kind or "")
    if kind == "item":
        return f"work:item:{item_id}"
    if kind == "epic_task":
        return f"work:epic_task:{epic_id}:{task_num}"
    if kind == "process":
        return f"work:process:{process_key}"
    if kind == "steering":
        return f"work:steering:{project_id}"
    return f"work:{kind}:{rendered_target}"


def strategy_document_holding_key(project_id: Any, document_slug: Any) -> str:
    """Return the canonical identity for one strategy-document lock."""
    return f"strategy_document:{project_id}:{document_slug}"


def coordination_holding_key(lease_key: Any) -> str:
    """Return the canonical identity for one shared-operation lease."""
    return f"coordination:{lease_key}"


def _merge_target_entry(retained: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    """Fold another authority facet into the target row already retained."""
    if incoming.get("path_count") is not None:
        retained["path_count"] = int(retained.get("path_count") or 0) + int(
            incoming["path_count"]
        )
    for key, value in incoming.items():
        if key not in retained or retained[key] is None:
            retained[key] = value


def group_session_holdings(
    observations: Iterable[Mapping[str, Any]],
    *,
    previous_limit: int,
) -> dict[str, Any]:
    """Partition and bound one session's holding observations.

    Each observation must carry a stable ``target_key`` and a ``released_at``
    value.  ``released_at is None`` means the target is currently held. The
    first row for a target is the display row retained within its partition. A
    current row always removes the same target from previous history,
    regardless of input order.
    """
    if isinstance(previous_limit, bool) or previous_limit < 0:
        raise ValueError(
            "previous_limit must be a non-negative integer; pass the "
            "render surface's row budget"
        )

    current: dict[str, dict[str, Any]] = {}
    previous: dict[str, dict[str, Any]] = {}
    for raw in observations:
        entry = dict(raw)
        target_key = str(entry.get("target_key") or "").strip()
        if not target_key:
            raise ValueError(
                "holding observation requires target_key; derive it from the "
                "authority target before grouping"
            )
        entry["target_key"] = target_key
        if entry.get("released_at") is None:
            retained = current.setdefault(target_key, entry)
            if retained is not entry:
                _merge_target_entry(retained, entry)
            previous.pop(target_key, None)
        elif target_key not in current:
            retained = previous.setdefault(target_key, entry)
            if retained is not entry:
                _merge_target_entry(retained, entry)

    previous_rows = list(previous.values())
    shown_previous = previous_rows[:previous_limit]
    return {
        "current": list(current.values()),
        "previous": shown_previous,
        "previous_remainder": len(previous_rows) - len(shown_previous),
    }


__all__ = [
    "SESSION_PATH_HOLDING_KEY",
    "coordination_holding_key",
    "group_session_holdings",
    "strategy_document_holding_key",
    "work_holding_key",
]
