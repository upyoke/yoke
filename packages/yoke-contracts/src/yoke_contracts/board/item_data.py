"""Named item values and connection-free board classification."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Optional

from yoke_contracts.timestamps import parse_instant

from yoke_contracts.project_contract.board_art.emoji import (
    STATUS_EMOJI as _STATUS_EMOJI_PREFIX,
)
from yoke_contracts.board.status import status_to_board_bucket
from yoke_contracts.public_ref import format_item_ref
from yoke_contracts.merge_queue_status import render_merge_queue_status

# ---------------------------------------------------------------------------
# Named tuple for classified item rows
# ---------------------------------------------------------------------------


class ItemRow(NamedTuple):
    """A single classified backlog item row."""

    rank: int
    id: str  # Public item ref, e.g. "YOK-N".
    title: str
    workflow_id: str
    priority: str
    status: str
    progress: str
    epic_id: Optional[int]  # numeric epic_id (or None)
    project: str
    updated_at: datetime | None
    status_glyph: Optional[str] = None
    merge_queue_status: str = ""


# ---------------------------------------------------------------------------
# Status emoji mapping
# ---------------------------------------------------------------------------

# Status glyphs are owned by yoke_contracts.project_contract.board_art.emoji.STATUS_EMOJI
# (imported above as _STATUS_EMOJI_PREFIX) — the canonical dedup registry.


def status_emoji(
    status: str,
    celebration: Optional[str] = None,
    glyph: Optional[str] = None,
) -> str:
    """Map a status string to its emoji-prefixed display form.

    Returns ``"<emoji> <status>"`` for known statuses, or the raw status
    string for unrecognised values. When *celebration* is set and the status
    is ``done``, the celebration glyph replaces the normal ✅ (frontier
    inbox-zero flourish, kept consistent with the stats box and section header).
    """
    if celebration and status == "done":
        return f"{celebration} {status}"
    prefix = glyph if glyph is not None else _STATUS_EMOJI_PREFIX.get(status)
    if prefix is None:
        return status
    return f"{prefix} {status}"


# ---------------------------------------------------------------------------
# Priority rank mapping
# ---------------------------------------------------------------------------

_PRIORITY_RANK: Dict[str, int] = {
    "critical": 1,
    "high": 2,
    "medium": 3,
    "low": 4,
}


def priority_rank(priority: str) -> int:
    """Map a priority string to a numeric sort key (lower = higher priority)."""
    return _PRIORITY_RANK.get(priority, 5)


# ---------------------------------------------------------------------------
# Section buckets
# ---------------------------------------------------------------------------

# Maps board-domain buckets to section names.
# Maps current board-domain buckets into rendered board sections.
# Blocked items render in their own section instead of being folded
# into Active. Blocked-flag rows end up in `_BUCKET_TO_SECTION["blocked"] == "blocked"`.
_BUCKET_TO_SECTION: Dict[str, str] = {
    "done": "done",
    "frozen": "freezer",
    "implementing": "active",
    "blocked": "blocked",
    "reviewing": "active",
    "implemented": "active",
    "release": "active",
    "planning": "pipeline",
    "refined": "pipeline",
    "idea": "backlog",
    "unknown": "unknown",
}


# ---------------------------------------------------------------------------
# Item classification
# ---------------------------------------------------------------------------


class EpicStats(NamedTuple):
    """Pre-computed epic statistics for batched board rendering."""

    task_count: int
    progress: str  # "N/M (PP%)" or "—"


def classify_item_rows(
    rows: Iterable[Mapping[str, Any]], epic_stats: Mapping[int, EpicStats]
) -> Dict[str, List[ItemRow]]:
    """Classify named item facts without database or query-plan access."""
    sections: Dict[str, List[ItemRow]] = {
        "active": [],
        "pipeline": [],
        "backlog": [],
        "blocked": [],
        "freezer": [],
        "done": [],
        "unknown": [],
    }

    for row in rows:
        title = row["title"]
        workflow_id = row["workflow_id"]
        status = row["status"]
        priority = row["priority"]
        frozen_int = row["frozen_int"]
        blocked_int = row["blocked_int"]
        numid = row["numid"]
        project_display = row["project_display"]
        updated_at = row["updated_at"]
        project_slug = row["project_slug"]
        public_item_prefix = row["public_item_prefix"]
        project_sequence = row["project_sequence"]
        status_glyph = row["status_glyph"]
        status_bucket = row["status_bucket"]
        merge_queue_enqueued_at = row["merge_queue_enqueued_at"]
        merge_queue_landed_at = row["merge_queue_landed_at"]
        generated_children = row["generated_children"]
        yok_id = format_item_ref(project_slug, public_item_prefix, project_sequence)

        eff_epic: Optional[int] = (
            int(numid) if generated_children == "epic_tasks" else None
        )

        # Compute progress — use precomputed stats when available
        if eff_epic is not None:
            es = epic_stats.get(eff_epic)
            progress = es.progress if es is not None else "—"
        else:
            progress = "—"

        rank = priority_rank(priority)

        item_row = ItemRow(
            rank=rank,
            id=yok_id,
            title=title,
            workflow_id=workflow_id,
            priority=priority,
            status=status,
            progress=progress,
            epic_id=eff_epic,
            project=project_display,
            updated_at=parse_instant(updated_at) if updated_at is not None else None,
            status_glyph=str(status_glyph) if status_glyph else None,
            merge_queue_status=render_merge_queue_status(
                merge_queue_enqueued_at,
                merge_queue_landed_at,
                item_status=status,
            ),
        )

        # Classify using the domain bucket function
        bucket = status_to_board_bucket(
            status,
            frozen_value=frozen_int,
            blocked_value=blocked_int,
            workflow_id=workflow_id,
            workflow_stage_bucket=(str(status_bucket) if status_bucket else None),
        )
        section = _BUCKET_TO_SECTION.get(bucket, "unknown")
        sections[section].append(item_row)

    # Sort active/pipeline/backlog/blocked/freezer by priority rank, then item id.
    for section_name in (
        "active",
        "pipeline",
        "backlog",
        "blocked",
        "freezer",
        "unknown",
    ):
        sections[section_name].sort(key=lambda r: (r.rank, r.id))

    sections["done"].sort(
        key=lambda r: (r.updated_at is not None, r.updated_at, r.id), reverse=True
    )

    return sections
