"""Board dashboard widgets.

Submodules: widgets_activity, widgets_velocity_meter, widgets_badges.
"""

# Activity, weather, and sparkline rendering
from yoke_contracts.board.widgets_activity import (  # noqa: F401
    _BLOCKS,
    _active_day_set,
    _build_sparkline,
    _compute_lifetime_activity,
    _compute_streak,
    _date_range,
    _merge_counts,
    _project_filter,
    render_velocity_sparkline,
    render_weather,
)

# Type, age, and achievement badges
from yoke_contracts.board.widgets_badges import (  # noqa: F401
    _allocate_proportional,
    _compute_achievement_streak,
    _streak_tier,
    render_achievement_badges,
    render_age_heatmap,
    render_type_badges,
)

# Git velocity meter
from yoke_contracts.board.widgets_velocity_meter import (  # noqa: F401
    _parse_shortstat,
    render_velocity_meter,
)
