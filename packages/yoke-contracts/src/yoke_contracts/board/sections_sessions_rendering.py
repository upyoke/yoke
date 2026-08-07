"""Presentation helpers for board session tables."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import item_ref
from yoke_contracts.board.utils import display_width
from yoke_contracts.item_ref import format_item_ref
from yoke_contracts.session_lane import (
    UNRESOLVED_EXECUTION_LANE,
    lane_is_unresolved,
    lane_presentation,
)

_RENDERED_ITEM_REF_RE = re.compile(r"^[A-Za-z]+-\d")
_MODE_EMOJI: Dict[str, str] = {
    "hook": "🪝",
    "refine": "📝",
    "polish": "✨",
    "charge": "⚡",
    "dash": "💨",
    "strategize": "🧠",
    "escalate": "🚨",
    "manual": "🔧",
    "operator": "🦾",
    "resume": "🔄",
    "advance": "⏩",
    "wait": "⏳",
    "conduct": "🎼",
    "shepherd": "🧑‍🌾",
    "usher": "🎬",
    "curate": "🧹",
    "doctor": "🩺",
    "simulate": "🔮",
    "idea": "💡",
    "wrapup": "🧾",
    "do": "🎮",
    "feed": "🍴",
    "plan": "📌",
}


def _format_session_age(iso_ts: str) -> str:
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        secs = int((datetime.now(timezone.utc) - ts).total_seconds())
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m"
        if secs < 86400:
            return f"{secs // 3600}h"
        return f"{secs // 86400}d"
    except (ValueError, TypeError):
        return iso_ts[:16] if iso_ts else "?"


def _claims_for_session(
    db: BoardDBLike, session_id: str, active_only: bool
) -> List[Tuple]:
    released_filter = "AND wc.released_at IS NULL" if active_only else ""
    return db.query_quiet(
        f"""
        SELECT wc.item_id, wc.epic_id, wc.task_num, wc.claim_type,
               wc.claimed_at, wc.released_at, wc.release_reason,
               wc.target_kind, wc.process_key
        FROM work_claims wc
        WHERE wc.session_id = %s
        {released_filter}
        ORDER BY wc.claimed_at DESC
        """,
        (session_id,),
    )


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


def _render_claim_target(
    item_id,
    epic_id: Optional[int],
    task_num: Optional[int],
    process_key: Optional[str] = None,
    *,
    db: Optional[BoardDBLike] = None,
) -> str:
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
    return "?"


__all__ = [
    "_MODE_EMOJI",
    "_aligned_table",
    "_claims_for_session",
    "_format_session_age",
    "_render_claim_target",
    "_render_lane",
]
