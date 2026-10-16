"""Collect project timeline facts and compose the live timeline view."""

from __future__ import annotations

from typing import List, Optional, Tuple

from yoke_contracts.board.config import BoardConfig
from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.zen_data import (
    _WIDTH,
    _zen_check_visibility,
    _zen_compute_window,
    _zen_compute_zones,
    _zen_item_positions,
    _zen_query_items,
    _zen_query_projects,
    _zen_queued_count,
)
from yoke_contracts.board.zen_labels import (
    _parse_extra_stopwords,
    _zen_compute_labels,
)

from yoke_contracts.board.timeline_data import render_timeline_rows


def collect_timeline_rows(
    db: BoardDBLike,
    config: BoardConfig,
    scope: str,
    *,
    vision_count: int = 0,
    vision_project: Optional[str] = None,
) -> list[dict]:
    """Collect named timeline facts for the authorized project scope."""
    result = []
    for project, emoji in _zen_query_projects(db, scope):
        facts = collect_timeline_project(
            db,
            project,
            emoji,
            _WIDTH,
            vision_count if project == vision_project else 0,
            max(0, int(config.timeline_label_days or 0)),
            max(0, int(config.timeline_label_df_cap_pct or 0)),
            _parse_extra_stopwords(config.timeline_extra_stopwords),
            max(0, int(config.timeline_label_min or 0)),
        )
        if facts is not None:
            result.append(facts)
    return result


def render_zen_widget(
    db: BoardDBLike,
    config: BoardConfig,
    scope: str,
    active_count: int,
    pipeline_count: int,
    backlog_count: int,
    vision_entries: List[Tuple[str, str]] = (),
    vision_project: Optional[str] = None,
) -> List[str]:
    """Read timeline facts and render them with the checkout-local VISION labels."""
    if not _zen_check_visibility(
        config.timeline_widget, active_count, pipeline_count, backlog_count
    ):
        return []
    vision = list(vision_entries)
    return render_timeline_rows(
        collect_timeline_rows(
            db, config, scope, vision_count=len(vision), vision_project=vision_project
        ),
        vision,
        vision_project,
    )


def collect_timeline_project(
    db: BoardDBLike,
    project: str,
    emoji: str,
    width: int,
    vision_count: int,
    label_days: int = 0,
    df_cap_pct: int = 0,
    extra_stops: frozenset = frozenset(),
    min_labels: int = 0,
) -> dict | None:
    """Read the facts for a single project timeline."""
    window = _zen_compute_window(db, project)
    if not window:
        return None

    items = _zen_query_items(db, project, window)
    if not items:
        return None

    queued = _zen_queued_count(db, project)
    has_queued = queued > 0

    zones = _zen_compute_zones(width, True, has_queued, vision_count)
    past_width = 80  # default
    for zname, zwidth, _zcol in zones:
        if zname == "past":
            past_width = zwidth
            break

    future_width = width - 4 - past_width - 4  # 4 emoji, 4 present
    if future_width < 0:
        future_width = 0

    labels = _zen_compute_labels(
        db, project, window, label_days, df_cap_pct, extra_stops, min_labels
    )
    positions = _zen_item_positions(db, project, window, past_width)

    return {
        "project": project,
        "emoji": emoji,
        "queued": queued,
        "past_width": past_width,
        "future_width": future_width,
        "labels": labels,
        "positions": positions,
    }


__all__ = ["collect_timeline_rows", "render_zen_widget"]
