"""Done-transition cascade facade."""

from __future__ import annotations

from yoke_core.engines.done_transition_discovery import (  # noqa: F401
    _load_discovery_metadata,
    _apply_discovery_scan,
)
from yoke_core.engines.done_transition_status import (  # noqa: F401
    _populate_merged_at,
    _update_status_to_done,
    _cascade_epic_tasks_to_done,
    _batch_github_sync_tasks,
)
from yoke_core.engines.done_transition_merge_ops import (  # noqa: F401
    _cross_project_commit_guard,
    _pre_merge_commit,
    _do_merge,
    _cleanup_stale_branches,
    _cleanup_trial_branches,
    _verify_cwd_after_merge,
    _schema_gate,
    _handle_already_done,
)
