"""Per-project GitHub sync mode vocabulary.

Single source of truth for the ``projects.github_sync_mode`` values,
shared by the core reader (``yoke_core.domain.projects_github_sync_mode``)
and the CLI flag surface (``yoke projects create/update
--github-sync-mode``).

``enabled``  — backlog items and epic tasks mirror to GitHub issues.
``disabled`` — the backlog lives only in the Yoke DB; every GitHub issue-sync
               surface skips or refuses for the project.
"""

from __future__ import annotations


GITHUB_SYNC_ENABLED = "enabled"
GITHUB_SYNC_DISABLED = "disabled"
VALID_GITHUB_SYNC_MODES = frozenset(
    {
        GITHUB_SYNC_ENABLED,
        GITHUB_SYNC_DISABLED,
    }
)


__all__ = [
    "GITHUB_SYNC_DISABLED",
    "GITHUB_SYNC_ENABLED",
    "VALID_GITHUB_SYNC_MODES",
]
