"""Presentation helpers for board session tables."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import item_ref
from yoke_contracts.board.utils import display_width
from yoke_contracts.coordination_claim_keys import COORDINATION_TARGET_KINDS
from yoke_contracts.item_ref import format_item_ref
from yoke_contracts.session_lane import (
    UNRESOLVED_EXECUTION_LANE,
    lane_is_unresolved,
    lane_presentation,
)

_RENDERED_ITEM_REF_RE = re.compile(r"^[A-Za-z]+-\d")


def _format_session_age(iso_ts: str) -> str:
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        secs = max(0, int((datetime.now(timezone.utc) - ts).total_seconds()))
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m"
        if secs < 86400:
            return f"{secs // 3600}h"
        return f"{secs // 86400}d"
    except (ValueError, TypeError):
        return iso_ts[:16] if iso_ts else "?"


def _claims_for_session(db: BoardDBLike, session_id: str) -> List[Tuple]:
    params = (session_id,)
    scope_sql = """
        SELECT wc.scope, wc.claim_type, wc.claimed_at, wc.released_at,
               wc.release_reason, wc.target_kind
        FROM work_claims wc
        WHERE wc.session_id = %s
        ORDER BY wc.claimed_at DESC
        """
    rows = db.query_quiet(
        scope_sql,
        params,
    )
    claims: List[Tuple] = []
    for row in rows:
        raw_scope = row[0]
        try:
            scope = raw_scope if isinstance(raw_scope, dict) else json.loads(raw_scope)
        except (TypeError, ValueError):
            scope = {}
        kind = str(row[5] or "")
        if kind in COORDINATION_TARGET_KINDS:
            continue
        claims.append(
            (
                scope.get("item_id") if kind == "item" else None,
                scope.get("epic_id") if kind == "epic_task" else None,
                scope.get("task_num") if kind == "epic_task" else None,
                row[1],
                row[2],
                row[3],
                row[4],
                kind,
                scope.get("process_key") if kind == "process" else None,
                scope if isinstance(scope, dict) else {},
            )
        )
    return claims


def _render_lane(
    lane: Optional[str], presentation: Optional[Dict[str, str]] = None
) -> str:
    if lane_is_unresolved(lane):
        return f"⚠️ {UNRESOLVED_EXECUTION_LANE}"
    metadata = presentation or lane_presentation(lane)
    label, glyph = metadata["label"], metadata["glyph"]
    return f"{glyph} {label}" if glyph else label


def _aligned_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    ncols = len(headers)
    widths = [display_width(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row[:ncols]):
            widths[index] = max(widths[index], display_width(cell))

    def format_row(cells: list[str]) -> str:
        padded = [
            cells[index] + " " * max(widths[index] - display_width(cells[index]), 0)
            for index in range(ncols)
        ]
        return "| " + " | ".join(padded) + " |"

    separator = "| " + " | ".join("-" * width for width in widths) + " |"
    return [format_row(headers), separator, *(format_row(row) for row in rows)]


def _compact_scope(scope: dict) -> str:
    return json.dumps(scope, sort_keys=True, separators=(",", ":"))


def _render_claim_target(
    item_id,
    epic_id: Optional[int],
    task_num: Optional[int],
    process_key: Optional[str] = None,
    *,
    db: Optional[BoardDBLike] = None,
    target_kind: str = "",
    scope: Optional[dict] = None,
) -> str:
    payload = scope if isinstance(scope, dict) else {}
    kind = str(target_kind or "")
    if process_key:
        return f"🔩 {process_key}"
    if item_id is not None:
        if db is not None:
            try:
                return item_ref(db, int(item_id))
            except Exception:
                pass
        item_str = str(item_id)
        if _RENDERED_ITEM_REF_RE.match(item_str):
            return item_str
        return format_item_ref(None, None, item_str)
    if epic_id is not None and task_num is not None:
        if db is not None:
            try:
                return f"{item_ref(db, int(epic_id))} T{task_num:03d}"
            except Exception:
                pass
        return f"{format_item_ref(None, None, epic_id)} T{task_num:03d}"
    if kind:
        return f"{kind}:{_compact_scope(payload)}"
    return "?"


__all__ = [
    "_aligned_table",
    "_claims_for_session",
    "_format_session_age",
    "_render_claim_target",
    "_render_lane",
]
