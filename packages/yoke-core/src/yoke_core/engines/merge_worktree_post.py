"""Merge-worktree post-merge phase facade."""

from __future__ import annotations

from yoke_core.engines.merge_worktree_post_local import do_local_merge  # noqa: F401
from yoke_core.engines.merge_worktree_pr import (  # noqa: F401
    _current_origin_target_sha,
    _ensure_target_pushed,
    do_pr_merge,
)
from yoke_core.engines.merge_worktree_pr_setup import (  # noqa: F401
    _discover_existing_pr,
)
from yoke_core.engines.merge_worktree_ci import _wait_for_ci  # noqa: F401

from yoke_core.engines.merge_worktree_post_helpers import (  # noqa: F401
    _post_merge_cleanup,
    _sync_local_target,
    _schema_refresh,
    _yoke_state_dir,
    _regenerate_views,
    _regenerate_views_or_exit5,
    _ensure_target_branch,
    _chdir_out_of_doomed_worktree,
)
