"""Collect the shared 120-day activity, code, issue and strategy series."""

from __future__ import annotations

from typing import Optional

from yoke_contracts.board.config import BoardConfig
from yoke_contracts.project_contract.board_art import emoji as E
from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.momentum_series import (
    activity_units_by_day,
    issues_done_by_day,
    lines_changed_by_day,
    strategy_bytes_by_day,
)
from yoke_contracts.board.widgets_activity import (
    _date_range,
)
from yoke_contracts.board.widgets_code_days import (
    _scope_project_ids,
)

# ---------------------------------------------------------------------------
# Velocity-meter-only emoji constants
# ---------------------------------------------------------------------------

_FLOPPY = E.VELOCITY_CODE
_PACKAGE = E.VELOCITY_DELIVERY
_COMPASS = E.VELOCITY_STRATEGY


# ---------------------------------------------------------------------------
# Velocity meter (120-day, 4 rows)
# ---------------------------------------------------------------------------


def collect_velocity_series(
    db: BoardDBLike, config: BoardConfig, scope: str, repo_root: Optional[str] = None
) -> dict:
    """Render the 120-day velocity meter (4 sparkline rows).

    Returns a list of 4 lines, or ``None`` if disabled or no data.
    ``repo_root`` is retained for call-site compatibility; code meters
    read ``project_code_days`` rather than local git.

    Row order: activity, code lines, issues done, strategy size change.
    """
    del repo_root  # ingest-only; meters read the control-plane rollup
    days = 120
    dates = _date_range(days)

    project_ids = _scope_project_ids(db, scope)
    act_counts = activity_units_by_day(db, project_ids, days=days)
    effort_counts = lines_changed_by_day(db, project_ids, days=days)
    del_counts = issues_done_by_day(db, project_ids, days=days)
    sml_counts = strategy_bytes_by_day(db, project_ids, days=days)

    return dict(
        dates=dates,
        activity=act_counts,
        code=effort_counts,
        issues=del_counts,
        strategy=sml_counts,
    )


def render_velocity_meter(db, config, scope, repo_root=None):
    from yoke_contracts.board.widget_data import render_velocity_series

    return render_velocity_series(
        **collect_velocity_series(db, config, scope, repo_root)
    )
