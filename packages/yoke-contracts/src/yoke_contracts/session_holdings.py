"""Shared session-holdings grouping for board and roster renderers.

Readers contribute display-shaped observations in their intended display order. This
module owns the semantics that both session surfaces must share: current wins
over previous, released steering seats lead history, repeated claim targets retain
their latest release and count, and callers supply the previous-row budget.
"""

from __future__ import annotations

from datetime import datetime, timezone
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
    steering_docs: Iterable[Any] = (),
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
        return steering_holding_key(project_id, steering_docs)
    return f"work:{kind}:{rendered_target}"


def steering_holding_key(project_id: Any, document_slugs: Iterable[Any]) -> str:
    """Identify a steering seat by project and the documents it covered."""
    documents = sorted({text for slug in document_slugs if (text := str(slug or ""))})
    suffix = f":{','.join(documents)}" if documents else ""
    return f"work:steering:{project_id}{suffix}"


def strategy_document_holding_key(project_id: Any, document_slug: Any) -> str:
    """Return the canonical identity for one strategy-document lock."""
    return f"strategy_document:{project_id}:{document_slug}"


def steering_hold_window_key(
    project_id: Any,
    claimed_at: Any,
    released_at: Any,
) -> tuple[str, str, str]:
    """Identify one project's steering hold window across board reads."""
    return (str(project_id), str(claimed_at or ""), str(released_at or ""))


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    stamp = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _release_timestamp(value: Any) -> datetime | None:
    try:
        return _timestamp(value)
    except (TypeError, ValueError):
        return None


def pair_steering_document_slugs(
    candidates: Iterable[Mapping[str, Any]],
) -> dict[Any, list[str]]:
    """Pair same-session/project document candidates to steering holds.

    Current seats pair with current locks. Released seats pair with released
    locks whose hold windows overlapped. Callers supply only candidates from
    the same session and project; this function owns the temporal rule shared
    by board and dashboard projections.
    """
    paired: dict[Any, set[str]] = {}
    for candidate in candidates:
        claim_key = candidate.get("claim_key")
        if claim_key is None:
            claim_key = candidate.get("claim_id")
        slug = str(candidate.get("strategy_doc_slug") or "")
        if claim_key is None or not slug:
            continue
        claim_released = candidate.get("claim_released_at")
        doc_released = candidate.get("doc_released_at")
        matches = claim_released is None and doc_released is None
        if claim_released is not None and doc_released is not None:
            claim_start = _timestamp(candidate.get("claim_claimed_at"))
            claim_end = _timestamp(claim_released)
            doc_start = _timestamp(candidate.get("doc_registered_at"))
            doc_end = _timestamp(doc_released)
            matches = bool(
                claim_start
                and claim_end
                and doc_start
                and doc_end
                and doc_start <= claim_end
                and doc_end >= claim_start
            )
        if matches:
            paired.setdefault(claim_key, set()).add(slug)
    return {claim_key: sorted(slugs) for claim_key, slugs in paired.items()}


def coordination_holding_key(lease_key: Any) -> str:
    """Return the canonical identity for one shared-operation lease."""
    return f"coordination:{lease_key}"


def _merge_target_entry(retained: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    """Fold another authority facet into the target row already retained."""
    repeated_claim = (
        retained.get("released_at") is not None
        and incoming.get("released_at") is not None
        and retained.get("holding_kind") == incoming.get("holding_kind") == "work_claim"
    )
    if repeated_claim:
        retained["occurrence_count"] = int(retained.get("occurrence_count") or 1) + int(
            incoming.get("occurrence_count") or 1
        )
    retained_release = _release_timestamp(retained.get("released_at"))
    incoming_release = _release_timestamp(incoming.get("released_at"))
    if incoming_release and (
        retained_release is None or incoming_release > retained_release
    ):
        retained["released_at"] = incoming["released_at"]
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
    first row for a target is the display row retained within its partition,
    enriched with the latest release and repeated-claim count. A current row
    always removes the same target from previous history, regardless of input
    order. Released steering targets sort ahead of the remaining history before
    the caller's row budget is applied.
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

    previous_rows = sorted(
        previous.values(),
        key=lambda entry: entry.get("target_kind") != "steering",
    )
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
    "pair_steering_document_slugs",
    "steering_hold_window_key",
    "steering_holding_key",
    "strategy_document_holding_key",
    "work_holding_key",
]
