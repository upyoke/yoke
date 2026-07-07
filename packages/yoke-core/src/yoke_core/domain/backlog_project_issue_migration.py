"""Backlog project-issue migration bridge — when an item's `project`
field changes across repo boundaries, transfer the linked GitHub issue
to the new repo via `backlog_github_sync.migrate_issue_to_repo` before
the project field write commits.
"""

from __future__ import annotations

from typing import Any, Optional, TextIO

from yoke_core.domain import backlog_rendering as _rendering
from yoke_core.domain.project_identity import DEFAULT_PROJECT_SLUG


def _maybe_migrate_project_issue(
    conn: Any,
    item_dict: dict[str, Any],
    target_project: str,
    out: TextIO,
) -> tuple[bool, Optional[str]]:
    """Migrate a GitHub issue when a project update crosses repo boundaries."""
    github_issue = item_dict.get("github_issue")
    if not github_issue or github_issue == "null":
        return True, None

    old_project = item_dict.get("project") or DEFAULT_PROJECT_SLUG
    old_repo = _rendering._resolve_project_github_repo(conn, old_project)
    new_repo = _rendering._resolve_project_github_repo(conn, target_project)

    if not old_repo or not new_repo or old_repo == new_repo:
        return True, None

    from yoke_core.domain import backlog_github_sync

    issue_num = str(github_issue).lstrip("#")
    rc = backlog_github_sync.migrate_issue_to_repo(
        str(item_dict["id"]),
        issue_num,
        old_repo,
        new_repo,
        target_project,
        conn=conn,
        stdout=out,
        stderr=out,
    )
    if rc != 0:
        return False, f"GitHub issue migration failed for YOK-{item_dict['id']}. Project field NOT updated."
    return True, None


__all__ = ["_maybe_migrate_project_issue"]
