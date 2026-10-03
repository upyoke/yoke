"""Validated ordering and continuation for compact observation lists."""

from __future__ import annotations

import base64

from yoke_core.domain.json_helper import dumps_compact, loads_text

ROSTER_PREVIEW_LENGTH = 240

SORT_COLUMNS = {
    "timestamp": "COALESCE(o.timestamp,'')",
    "preview": f"SUBSTR(COALESCE(o.body,''),1,{ROSTER_PREVIEW_LENGTH})",
    "category": "COALESCE(o.category,'')",
    "context": "COALESCE(o.context,'')",
    "reviewed_at": "COALESCE(o.reviewed_at,'')",
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


def continuation(cursor, sort, project_ids):
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
        if not isinstance(value, str):
            raise ValueError
    except Exception as exc:
        raise ValueError(
            "Cursor is malformed or belongs to another sort/project selection; Reload the Ouroboros page"
        ) from exc
    expression = SORT_COLUMNS[sort["column"]]
    comparison = ">" if sort["direction"] == "asc" else "<"
    return (
        f"({expression} {comparison} {{p}} OR ({expression} = {{p}} AND o.id {comparison} {{p}}))",
        [value, value, entry_id],
    )


def encode_continuation(row, sort, project_ids):
    raw = dumps_compact(
        {
            "id": row["id"],
            "value": row["_sort_value"],
            "sort": sort,
            "projects": sorted(project_ids),
        }
    )
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
