"""Section rendering — epic progress, task sub-rows, and the section table.

Owns ``epic_progress``, ``epic_task_rows``, batched epic-task precomputes,
``task_expanded_count``, and ``render_section`` — the helpers the renderer
calls per section to emit the markdown table for active / pipeline / backlog /
freezer / done.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.sections_classify import (
    EpicStats,
    ItemRow,
    _project_filter_sql,
    precompute_epic_stats,
    status_emoji,
)
from yoke_contracts.lifecycle_status import TASK_TERMINAL_SUCCESS

EpicTaskRow = Tuple[int, str, str]

# ---------------------------------------------------------------------------
# Epic progress
# ---------------------------------------------------------------------------


def epic_progress(db: BoardDBLike, epic_id: Optional[int]) -> str:
    """Return progress string for an epic: ``"N/M (PP%)"`` or ``"—"``.

    Args:
        db: Open database handle.
        epic_id: Numeric epic ID.

    Returns:
        Progress string or em-dash if no tasks exist.
    """
    if epic_id is None:
        return "—"

    _tts_in = ", ".join(f"'{s}'" for s in sorted(TASK_TERMINAL_SUCCESS))
    row = db.query(
        f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status IN ({_tts_in}) THEN 1 ELSE 0 END) AS done
        FROM epic_tasks
        WHERE epic_id = %s
        """,
        (epic_id,),
    )

    if not row:
        return "—"

    total, done = row[0]
    if not total or total == 0:
        return "—"

    done = done or 0
    pct = done * 100 // total
    return f"{done}/{total} ({pct}%)"


# ---------------------------------------------------------------------------
# Epic task sub-rows
# ---------------------------------------------------------------------------


def epic_task_rows(
    db: BoardDBLike,
    epic_id: int,
    parent_id_padded: str,
    celebration: Optional[str] = None,
) -> List[str]:
    """Return markdown table rows for each task under an epic.

    Args:
        db: Open database handle.
        epic_id: Numeric epic ID.
        parent_id_padded: Padded parent ID string.
            Used to determine padding width for alignment.
        celebration: Frontier inbox-zero glyph that overrides ``done`` rows.

    Returns:
        List of markdown table row strings.
    """
    rows = db.query(
        "SELECT task_num, title, status FROM epic_tasks WHERE epic_id = %s ORDER BY task_num",
        (epic_id,),
    )
    return _format_epic_task_rows(rows, parent_id_padded, celebration)


def _format_epic_task_rows(
    rows: Sequence[EpicTaskRow],
    parent_id_padded: str,
    celebration: Optional[str] = None,
) -> List[str]:
    if not rows:
        return []

    # Pad empty ID cell to match parent YOK-N width for column alignment
    pad = " " * len(parent_id_padded)

    result: List[str] = []
    for task_num, title, task_status in rows:
        tnum_pad = f"{task_num:03d}"
        # Escape pipe chars in title
        title_clean = title.replace("|", "∣") if title else ""
        tstat_emoji = status_emoji(task_status or "", celebration)
        result.append(
            f"| {pad} | {tstat_emoji} | | | task | | └ {tnum_pad}: {title_clean} |"
        )

    return result


def precompute_epic_task_rows(
    db: BoardDBLike,
    scope: str,
) -> Dict[int, List[EpicTaskRow]]:
    """Batch-query task rows for all epics in the rendered scope."""
    pf = _project_filter_sql(scope, db=db)
    rows = db.query_quiet(
        f"""
        SELECT et.epic_id, et.task_num, et.title, et.status
        FROM epic_tasks et
        JOIN items i ON i.id = et.epic_id
        WHERE 1=1{pf}
        ORDER BY et.epic_id, et.task_num
        """,
    )
    result: Dict[int, List[EpicTaskRow]] = {}
    for epic_id, task_num, title, status in rows:
        result.setdefault(int(epic_id), []).append(
            (int(task_num), title or "", status or "")
        )
    return result


# ---------------------------------------------------------------------------
# Task-expanded counting
# ---------------------------------------------------------------------------


def precompute_epic_task_counts(
    db: BoardDBLike,
    scope: str,
) -> Dict[int, int]:
    """Query epic_id -> task count for all epics with tasks.

    .. deprecated::
        Use :func:`precompute_epic_stats` which returns both task counts
        and progress strings in a single query.

    Args:
        db: Open database handle.
        scope: Project scope for filtering.

    Returns:
        Dict mapping epic_id to task count.
    """
    return {eid: es.task_count for eid, es in precompute_epic_stats(db, scope).items()}


def task_expanded_count(
    items: List[ItemRow],
    epic_task_counts: Dict[int, int],
) -> int:
    """Compute task-expanded count for a list of items.

    Epics with tasks expand to N units (one per task) instead of 1.

    Args:
        items: List of classified item rows.
        epic_task_counts: Pre-computed epic_id -> task count mapping.

    Returns:
        Task-expanded total count.
    """
    count = len(items)
    for item in items:
        if item.type == "epic" and item.epic_id is not None:
            tc = epic_task_counts.get(item.epic_id, 0)
            if tc > 0:
                count += tc - 1  # replace 1 epic with N tasks
    return count


# ---------------------------------------------------------------------------
# Section rendering
# ---------------------------------------------------------------------------


def render_section(
    heading: str,
    items: List[ItemRow],
    epic_task_counts: Dict[int, int],
    db: BoardDBLike,
    emoji: str,
    max_id_width: int,
    epic_task_rows_by_epic: Optional[Mapping[int, Sequence[EpicTaskRow]]] = None,
    heading_count: Optional[int] = None,
    omitted_count: int = 0,
    celebration: Optional[str] = None,
) -> str:
    """Render a markdown table section with heading, items, and epic sub-rows.

    Args:
        heading: Section heading text (e.g. ``"Active"``).
        items: Classified and sorted item rows for this section.
        epic_task_counts: Pre-computed epic_id -> task count mapping.
        db: Open database handle (for epic task sub-row queries).
        emoji: Section emoji prefix (e.g. ``"\\U0001f535"``).
        max_id_width: Maximum ID column width for alignment.
        celebration: Frontier inbox-zero glyph that overrides ``done`` rows.

    Returns:
        Complete markdown section string, or empty string if no items.
    """
    if not items:
        return ""

    sec_count = task_expanded_count(items, epic_task_counts)
    count_label = (
        str(sec_count) if heading_count is None or heading_count == sec_count
        else f"showing {sec_count} of {heading_count}"
    )

    lines: List[str] = []

    # Heading with emoji prefix and item count badge
    if emoji:
        lines.append(f"### {emoji} {heading} ({count_label})")
    else:
        lines.append(f"### {heading} ({count_label})")
    lines.append("")

    # Table header
    id_header = "ID".ljust(max_id_width)
    id_sep = "-" * max_id_width + "--"
    lines.append(
        f"| {id_header} | Status | Project | Priority | Type | Progress | Title |"
    )
    lines.append(f"|{id_sep}|--------|---------|----------|------|----------|-------|")

    for item in items:
        rid_padded = item.id.ljust(max_id_width)
        rstat_emoji = status_emoji(item.status, celebration)
        lines.append(
            f"| {rid_padded} | {rstat_emoji} | {item.project} | "
            f"{item.priority} | {item.type} | {item.progress} | {item.title} |"
        )

        # Expand epic tasks as sub-rows
        if item.type == "epic" and item.epic_id is not None:
            if epic_task_rows_by_epic is None:
                sub_rows = epic_task_rows(db, item.epic_id, rid_padded, celebration)
            else:
                sub_rows = _format_epic_task_rows(
                    epic_task_rows_by_epic.get(item.epic_id, ()),
                    rid_padded,
                    celebration,
                )
            lines.extend(sub_rows)

    if omitted_count > 0:
        lines.append("")
        lines.append(f"*{omitted_count} older rows hidden by done_section_limit.*")

    lines.append("")
    return "\n".join(lines)


__all__ = [
    "EpicStats",
    "EpicTaskRow",
    "epic_progress",
    "epic_task_rows",
    "precompute_epic_task_counts",
    "precompute_epic_task_rows",
    "render_section",
    "task_expanded_count",
]
