"""Stats box rendering — the ``╔═ THE BOARD`` panel and its proportional meters.

Extracted from ``art_render`` so the header-assembly module stays focused (and
under the file line cap). ``art_render`` pastes the box returned here to the
right of the art grid.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from yoke_contracts.project_contract.board_art import emoji as E
from yoke_contracts.project_contract.board_art.config import BLACK, WHITE


def _render_stats_box(
    counts: Dict[str, int],
    total: int,
    celebration: Optional[str] = None,
) -> List[str]:
    """Render the 8-line stats box (was 7 before the added Blocked).

    Parameters
    ----------
    counts : dict
        Keys: ``active``, ``pipeline``, ``backlog``, ``blocked``, ``done``,
        ``frozen``.
    total : int
        Total units (for proportional meters).  When 0, renders narrow box.
    celebration : str or None
        When set, replaces the Done row emoji with this celebration emoji.

    Returns
    -------
    list[str]
        7 lines of the stats box.
    """
    active = counts.get("active", 0)
    pipeline = counts.get("pipeline", 0)
    backlog = counts.get("backlog", 0)
    done = counts.get("done", 0)
    frozen = counts.get("frozen", 0)
    blocked = counts.get("blocked", 0)
    title = "THE BOARD"
    done_emoji = celebration if celebration else E.DONE_EMOJI

    if total > 0:
        # Wide box with meters
        m_active = _render_meter(active, total, WHITE, BLACK)
        m_pipeline = _render_meter(pipeline, total, WHITE, BLACK)
        m_backlog = _render_meter(backlog, total, WHITE, BLACK)
        m_done = _render_meter(done, total, WHITE, BLACK)
        m_frozen = _render_meter(frozen, total, WHITE, BLACK)
        m_blocked = _render_meter(blocked, total, WHITE, BLACK)
        return [
            f" ╔═ {title}",
            f" ║ {E.ACTIVE_EMOJI} Active  {active:4d}  {m_active}",
            f" ║ {E.PIPELINE_EMOJI} Pipeline{pipeline:4d}  {m_pipeline}",
            f" ║ {E.BACKLOG_EMOJI} Backlog {backlog:4d}  {m_backlog}",
            f" ║ {E.BLOCKED_EMOJI} Blocked {blocked:4d}  {m_blocked}",
            f" ║ {E.FROZEN_EMOJI} Frozen  {frozen:4d}  {m_frozen}",
            f" ║ {done_emoji} Done    {done:4d}  {m_done}",
            " ╚═",
        ]
    else:
        return [
            f" ╔═ {title}",
            f" ║ {E.ACTIVE_EMOJI} Active     {active:4d}",
            f" ║ {E.PIPELINE_EMOJI} Pipeline   {pipeline:4d}",
            f" ║ {E.BACKLOG_EMOJI} Backlog    {backlog:4d}",
            f" ║ {E.BLOCKED_EMOJI} Blocked    {blocked:4d}",
            f" ║ {E.FROZEN_EMOJI} Frozen     {frozen:4d}",
            f" ║ {done_emoji} Done       {done:4d}",
            " ╚═",
        ]


def _render_meter(count: int, total: int, filled: str, empty: str) -> str:
    """Render a 10-cell proportional meter string."""
    if total <= 0:
        cells = 0
    else:
        cells = round(count * 10 / total)

    # Clamp to [0, 10]
    cells = max(0, min(10, cells))
    # Guarantee at least 1 cell for non-zero counts
    if count > 0 and cells < 1:
        cells = 1

    return filled * cells + empty * (10 - cells)
