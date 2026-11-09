"""Compose operator identity and checkout provenance for manual migration apply."""

from pathlib import Path
from typing import Any, Dict, Optional

from yoke_core.domain.migration_apply_attribution import (
    git_branch_and_commit, lookup_session_actor_id, require_attribution,
)


def collect_operator_attribution(
    control_conn: Any,
    *,
    worktree: Optional[Path] = None,
) -> Dict[str, str]:
    """Attribution for a manual apply. Missing ambient identity fails closed."""
    from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id

    session_id = resolve_ambient_session_id()
    actor_id = lookup_session_actor_id(control_conn, session_id)
    branch, commit = git_branch_and_commit(worktree or Path.cwd())
    return require_attribution(
        {
            "session_id": session_id,
            "actor_id": actor_id,
            "source_branch": branch,
            "source_commit": commit,
        }
    )


