"""Per-project GitHub sync mode vocabulary.

Single source of truth for the ``projects.github_sync_mode`` values,
shared by the core reader (``yoke_core.domain.projects_github_sync_mode``)
and the CLI flag surface (``yoke projects create/update
--github-sync-mode``).

``enabled``       — default; backlog items/epic tasks mirror to GitHub issues.
``backlog_only``  — the backlog lives only in the Yoke DB; every GitHub
                    issue sync surface skips or refuses for the project.
"""

from __future__ import annotations


GITHUB_SYNC_ENABLED = "enabled"
GITHUB_SYNC_BACKLOG_ONLY = "backlog_only"
VALID_GITHUB_SYNC_MODES = frozenset({
    GITHUB_SYNC_ENABLED,
    GITHUB_SYNC_BACKLOG_ONLY,
})


__all__ = [
    "GITHUB_SYNC_BACKLOG_ONLY",
    "GITHUB_SYNC_ENABLED",
    "VALID_GITHUB_SYNC_MODES",
]
