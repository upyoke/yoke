"""Validated ordering and continuation for compact observation lists."""

from __future__ import annotations

import base64

from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.json_helper import dumps_compact, loads_text

ROSTER_PREVIEW_LENGTH = 240

SORT_COLUMNS = {
    "timestamp": "o.timestamp",
    "preview": f"SUBSTR(COALESCE(o.body,''),1,{ROSTER_PREVIEW_LENGTH})",
    "category": "COALESCE(o.category,'')",
    "context": "COALESCE(o.context,'')",
    "reviewed_at": "o.reviewed_at",
    "project": "COALESCE(p.slug,'')",
}
SORT_DIRECTIONS = ("asc", "desc")


def normalize_sort(sort):
    if sort is None:
        return {"column": "timestamp", "direction": "desc"}
    if (
        not isinstance(sort, dict)
        or sort.get("column") not in SORT_COLUMNS
        or sort.get("direction") not in SORT_DIRECTIONS
    ):
        raise ValueError("Unknown Ouroboros sort column or direction")
    return {"column": sort["column"], "direction": sort["direction"]}


def continuation(cursor, sort, project_ids, *, conn):
    if not cursor:
        return "", []
    try:
        payload = loads_text(
            base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        )
        if payload["sort"] != sort or payload["projects"] != sorted(project_ids):
            raise ValueError
        entry_id = int(payload["id"])
        value = payload["value"]
        is_clock = sort["column"] in ("timestamp", "reviewed_at")
        if is_clock:
            value = parse_instant(value) if value is not None else None
            if value is None and sort["column"] != "reviewed_at":
                raise ValueError
        elif not isinstance(value, str):
            raise ValueError
    except Exception as exc:
        raise ValueError(
            "Cursor is malformed or belongs to another sort/project selection; Reload the Ouroboros page"
        ) from exc
    expression = SORT_COLUMNS[sort["column"]]
    comparison = ">" if sort["direction"] == "asc" else "<"
    if is_clock:
        if value is None:
            ties = f"({expression} IS NULL AND o.id {comparison} {{p}})"
            predicate = (
                f"({expression} IS NOT NULL OR {ties})" if comparison == ">" else ties
            )
            return predicate, [entry_id]
        value = instant_parameter(conn, value)
    predicate = f"({expression} {comparison} {{p}} OR ({expression} = {{p}} AND o.id {comparison} {{p}}))"
    if is_clock and comparison == "<":
        predicate = f"({expression} IS NULL OR {predicate})"
    return predicate, [value, value, entry_id]


def encode_continuation(row, sort, project_ids):
    value = row["_sort_value"]
    if sort["column"] in ("timestamp", "reviewed_at") and value is not None:
        value = format_instant(value)
    raw = dumps_compact(
        {
            "id": row["id"],
            "value": value,
            "sort": sort,
            "projects": sorted(project_ids),
        }
    )
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
