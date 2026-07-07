"""Board section classification + rendering.

Submodules: sections_classify, sections_render, sections_frontier, sections_sessions.
"""

# Item classification and display metadata
from yoke_contracts.board.sections_classify import (  # noqa: F401
    EpicStats,
    ItemRow,
    _project_filter_sql,
    classify_items,
    precompute_epic_stats,
    priority_rank,
    status_emoji,
)

# Section and epic task rendering
from yoke_contracts.board.sections_render import (  # noqa: F401
    EpicTaskRow,
    epic_progress,
    epic_task_rows,
    precompute_epic_task_counts,
    precompute_epic_task_rows,
    render_section,
    task_expanded_count,
)

# Frontier counts and consistency checks
from yoke_contracts.board.sections_frontier import (  # noqa: F401
    consistency_check,
    frontier_counts,
)

# Active session rows
from yoke_contracts.board.sections_sessions import render_sessions_section  # noqa: F401
