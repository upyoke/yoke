"""Select the next required setup or first-work action from current facts."""

from collections.abc import Mapping, Sequence
from typing import Any

from yoke_contracts.onboard_checklist import (
    FIRST_ITEM_DONE_ROW_ID,
    NEXT_ACTION_HOMES,
    REQUIRED_SETUP_ROW_IDS,
    ROW_IDS,
    STATUS_CONFIGURED,
    STATUS_VERIFIED,
    STATUS_NOT_NEEDED,
)


def select_next_action(
    rows: Sequence[Mapping[str, Any]],
    setup_readiness: Mapping[str, Any],
) -> dict[str, str] | None:
    by_id = {row["row_id"]: row for row in rows}
    for row_id in ROW_IDS:
        row = by_id.get(row_id)
        if row_id not in REQUIRED_SETUP_ROW_IDS or row is None:
            continue
        if row.get("status") not in (
            STATUS_CONFIGURED,
            STATUS_VERIFIED,
            STATUS_NOT_NEEDED,
        ):
            return _action(row)
    first = by_id.get(FIRST_ITEM_DONE_ROW_ID)
    if (
        setup_readiness.get("ready")
        and first
        and first.get("status")
        not in (
            STATUS_CONFIGURED,
            STATUS_VERIFIED,
        )
    ):
        return _action(first)
    return None


def _action(row: Mapping[str, Any]) -> dict[str, str]:
    return {
        "row_id": row["row_id"],
        "title": row["title"],
        "status": row["status"],
        "reason": row.get("reason") or row.get("blocker") or "setup_required",
        "command": row.get("recovery") or "/yoke onboard",
        "home": NEXT_ACTION_HOMES[row["layer"]],
    }
