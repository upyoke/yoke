"""Board render-from-payload assembly — client-tier, ships everywhere.

One assembly (``_assemble``) serves both halves of the board data layer:
collection records its query plan against a live DB (server side, in
``yoke_core.board.data``), rendering replays that plan from the recorded
payload here with no DB connection.

``render_board_from_payload`` renders ``BOARD.md`` from a fetched
``board.data.get`` payload — the ``yoke board rebuild`` composition over both
transports, never loading engine code. The live in-process ``render_board``
(which opens a ``BoardDB``) stays in ``yoke_core.board.renderer`` and
re-exports the names below.
"""

from __future__ import annotations

import sys
from typing import Dict, List, Optional

from yoke_contracts.board.art import ArtConfig, render_header, select_art
from yoke_contracts.project_contract.board_art.emoji import resolve_celebration
from yoke_contracts.board.config import BoardConfig
from yoke_contracts.board.phase_timer import PhaseRecorder, measure_phase
from yoke_contracts.board.project_scope import project_filter as _project_filter
from yoke_contracts.board.renderer_dashboard import render_dashboard
from yoke_contracts.board.renderer_sections import render_board_sections
from yoke_contracts.board.sections import (
    classify_items,
    consistency_check,
    frontier_counts,
    precompute_epic_stats,
    precompute_epic_task_rows,
    render_sessions_section,
    task_expanded_count,
)
from yoke_contracts.board.zen import render_zen_widget


def render_board_from_payload(
    payload: Dict,
    *,
    scope: str,
    config: BoardConfig,
    art_config: ArtConfig,
    seed: Optional[int] = None,
    repo_root: Optional[str] = None,
    vision_entries: Optional[List] = None,
    phase_recorder: PhaseRecorder | None = None,
) -> str:
    """Render BOARD.md from a fetched ``board.data.get`` payload.

    No DB connection: every read replays from the payload. ``config``,
    ``repo_root`` and ``vision_entries`` MUST be the same values the
    payload was collected with — they shape the query plan, and a
    divergent plan raises
    :class:`yoke_contracts.board.data.BoardDataMissError`.
    """
    from yoke_contracts.board.data import ReplayBoardDB
    from yoke_contracts.board.project_scope import scoped_project_visibility

    replay = ReplayBoardDB.from_payload(payload)
    setattr(replay, "_phase_recorder", phase_recorder)
    visible_project_ids = payload.get("visible_project_ids")
    with scoped_project_visibility(visible_project_ids):
        return _assemble(
            replay, config, art_config, scope, seed, repo_root,
            list(vision_entries or []),
        )


def _assemble(
    db,
    config: BoardConfig,
    art_config: ArtConfig,
    scope: str,
    seed: Optional[int],
    repo_root: Optional[str],
    vision_entries: Optional[List] = None,
) -> str:
    """Core assembly — both the recording and replay passes run this.

    ``db`` is any handle honoring the BoardDB seam (live ``BoardDB``,
    ``RecordingBoardDB``, or ``ReplayBoardDB``).
    """
    lines: List[str] = []

    # ------------------------------------------------------------------
    # 1. Classify items into sections (needed for counts and sections)
    # ------------------------------------------------------------------
    phase_recorder = getattr(db, "_phase_recorder", None)
    with measure_phase(phase_recorder, "epic_stats"):
        epic_stats = precompute_epic_stats(db, scope)
    with measure_phase(phase_recorder, "classify_items"):
        buckets = classify_items(db, scope, epic_stats=epic_stats)
    epic_task_counts = {eid: es.task_count for eid, es in epic_stats.items()}
    with measure_phase(phase_recorder, "epic_task_rows"):
        epic_task_rows_by_epic = (
            precompute_epic_task_rows(db, scope) if epic_task_counts else {}
        )

    has_items = any(bool(bucket) for bucket in buckets.values())

    # ------------------------------------------------------------------
    # 2. Header art
    # ------------------------------------------------------------------
    with measure_phase(phase_recorder, "frontier_counts"):
        fc = frontier_counts(db, scope, config.art_frontier_since)
    with measure_phase(phase_recorder, "header_art_select"):
        mode, variant = select_art(config, art_config, seed)
    section_stats = {
        "active": task_expanded_count(buckets.get("active", []), epic_task_counts),
        "pipeline": task_expanded_count(buckets.get("pipeline", []), epic_task_counts),
        "backlog": task_expanded_count(buckets.get("backlog", []), epic_task_counts),
        "blocked": task_expanded_count(buckets.get("blocked", []), epic_task_counts),
        "done": task_expanded_count(buckets.get("done", []), epic_task_counts),
        "frozen": task_expanded_count(buckets.get("freezer", []), epic_task_counts),
    }
    stats_total = sum(section_stats.values()) + task_expanded_count(
        buckets.get("unknown", []), epic_task_counts
    )
    stats_meter_total = min(stats_total, config.dashboard_meter_cap)
    # Resolve the celebration glyph once so the stats box, frontier grid/legend,
    # Done section header, and per-row done all show the same one this render.
    celebration = resolve_celebration(section_stats, mode, seed)
    with measure_phase(phase_recorder, "header_render"):
        header = render_header(
            db,
            config,
            art_config,
            mode,
            variant,
            fc,
            stats_counts=section_stats,
            stats_total=stats_meter_total,
            seed=seed,
            celebration=celebration,
        )
    if header:
        lines.append(header)

    # ------------------------------------------------------------------
    # 3. Dashboard widgets (between header art and section tables)
    # ------------------------------------------------------------------
    with measure_phase(phase_recorder, "dashboard"):
        lines.extend(render_dashboard(
            db, config, scope, buckets, epic_task_counts, repo_root,
        ))

    # ------------------------------------------------------------------
    # 4. Zen widget
    # ------------------------------------------------------------------
    active_count = section_stats["active"]
    pipeline_count = section_stats["pipeline"]
    backlog_count = section_stats["backlog"]

    with measure_phase(phase_recorder, "zen"):
        zen_lines = render_zen_widget(
            db, config, config.timeline_scope or scope,
            active_count, pipeline_count, backlog_count,
            vision_entries or [],
        )
    if zen_lines:
        lines.append("")
        lines.extend(zen_lines)

    # ------------------------------------------------------------------
    # 5. Sessions & Claims
    # ------------------------------------------------------------------
    with measure_phase(phase_recorder, "sessions"):
        sessions_text = render_sessions_section(
            db,
            show_recent=config.dashboard_recent_sessions,
            scope=config.dashboard_sessions_scope or scope,
        )
    if sessions_text:
        lines.append("")
        lines.append(sessions_text)

    # ------------------------------------------------------------------
    # 6. Section tables
    # ------------------------------------------------------------------
    if has_items:
        lines.append("")
        section_lines, rendered_expected_tasks = render_board_sections(
            db,
            config,
            scope,
            buckets,
            epic_task_counts,
            epic_task_rows_by_epic,
            phase_recorder,
            celebration=celebration,
        )
        lines.extend(section_lines)
    else:
        lines.append("*No backlog items yet. Create one with `/yoke idea`.*")
        lines.append("")

    # ------------------------------------------------------------------
    # 7. Consistency check (emit warning to stderr)
    # ------------------------------------------------------------------
    board_content = "\n".join(lines)
    with measure_phase(phase_recorder, "consistency_check"):
        expected_tasks = (
            rendered_expected_tasks if has_items else _count_expected_tasks(db, scope)
        )
        ok, msg = consistency_check(expected_tasks, board_content)
    if not ok:
        print(msg, file=sys.stderr)

    return board_content


def _count_expected_tasks(db, scope: str) -> int:
    """Count total expected epic task sub-rows from DB."""
    pf = _project_filter(scope)
    result = db.scalar(
        "SELECT COUNT(*) FROM epic_tasks et"
        " JOIN items i ON et.epic_id = i.id"
        f" WHERE i.type = 'epic'{pf}"
    )
    return result or 0
