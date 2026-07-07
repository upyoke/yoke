"""Board section rendering orchestration."""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from yoke_contracts.project_contract.board_art import emoji as E
from yoke_contracts.board.config import BoardConfig
from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.phase_timer import PhaseRecorder, measure_phase
from yoke_contracts.board.project_scope import project_filter as _project_filter
from yoke_contracts.board.sections import render_section, task_expanded_count
from yoke_contracts.board.sections_classify import ItemRow
from yoke_contracts.board.sections_render import EpicTaskRow


# Glyphs + labels are owned by board_emoji (stats box shares the same bucket
# vocabulary). "Active" and "Frozen" drop the legacy "Tickets"/"Freezer" wording.
_SECTIONS = [
    ("active", E.ACTIVE_LABEL, E.ACTIVE_EMOJI),
    ("blocked", E.BLOCKED_LABEL, E.BLOCKED_EMOJI),
    ("pipeline", E.PIPELINE_LABEL, E.PIPELINE_EMOJI),
    ("backlog", E.BACKLOG_LABEL, E.BACKLOG_EMOJI),
    ("freezer", E.FROZEN_LABEL, E.FROZEN_EMOJI),
    ("unknown", E.UNKNOWN_LABEL, E.UNKNOWN_EMOJI),
    ("done", E.DONE_LABEL, E.DONE_EMOJI),
]


def render_board_sections(
    db: BoardDBLike,
    config: BoardConfig,
    scope: str,
    buckets: Dict[str, List[ItemRow]],
    epic_task_counts: Dict[int, int],
    epic_task_rows_by_epic: Mapping[int, Sequence[EpicTaskRow]],
    phase_recorder: PhaseRecorder | None,
    celebration: Optional[str] = None,
) -> Tuple[List[str], int]:
    """Render all section tables and return expected rendered task rows.

    *celebration*, when set (frontier inbox-zero), overrides the Done section
    header glyph and every per-row ``done`` status to the celebration emoji.
    """
    with measure_phase(phase_recorder, "max_id_width"):
        max_numid = db.scalar(
            "SELECT MAX(id) FROM items WHERE 1=1" + (_project_filter(scope))
        )
    max_id_width = len(str(max_numid or 0)) + 4

    lines: List[str] = []
    rendered_expected_tasks = 0
    with measure_phase(phase_recorder, "sections"):
        for key, heading, emoji in _SECTIONS:
            section_items = buckets.get(key, [])
            rendered_items = section_items
            heading_count = None
            omitted_count = 0
            if (
                key == "done"
                and config.done_section_limit > 0
                and len(section_items) > config.done_section_limit
            ):
                rendered_items = section_items[:config.done_section_limit]
                heading_count = task_expanded_count(section_items, epic_task_counts)
                omitted_count = len(section_items) - len(rendered_items)
            rendered_expected_tasks += _count_rendered_epic_tasks(
                rendered_items, epic_task_rows_by_epic,
            )
            # Frontier inbox-zero: the Done section celebrates with the chosen
            # glyph in both its header and its per-row done statuses.
            section_emoji = (
                celebration if (key == "done" and celebration) else emoji
            )
            section_text = render_section(
                heading,
                rendered_items,
                epic_task_counts,
                db,
                section_emoji,
                max_id_width,
                epic_task_rows_by_epic,
                heading_count=heading_count,
                omitted_count=omitted_count,
                celebration=celebration,
            )
            if section_text:
                lines.append(section_text)
    return lines, rendered_expected_tasks


def _count_rendered_epic_tasks(
    items: Sequence[ItemRow],
    epic_task_rows_by_epic: Mapping[int, Sequence[EpicTaskRow]],
) -> int:
    total = 0
    for item in items:
        if item.type == "epic" and item.epic_id is not None:
            total += len(epic_task_rows_by_epic.get(item.epic_id, ()))
    return total


__all__ = ["render_board_sections"]
