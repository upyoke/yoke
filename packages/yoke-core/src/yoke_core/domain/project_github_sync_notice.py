"""Sync-mode result fields and recovery for repository binding changes."""

from __future__ import annotations

import shlex
from typing import Any

from yoke_contracts.project_contract.github_sync_mode import GITHUB_SYNC_DISABLED


def sync_mode_result(
    *, previous: str, current: str, slug: str, name: str,
    unbound: bool = False, public_repository: bool = False,
) -> dict[str, Any]:
    """Describe a mode change once for CLI and page consumers."""
    notice = None
    if previous != current and current == GITHUB_SYNC_DISABLED:
        recovery = "bind a repository again, then run " if unbound else "run "
        command = (
            f"yoke projects update --slug {shlex.quote(slug)} "
            f"--name {shlex.quote(name)} --github-sync-mode enabled"
        )
        if public_repository:
            command += " --allow-public-github-sync"
        notice = f"Issue sync was turned off. To turn it back on, {recovery}{command}."
    return {
        "previous_sync_mode": previous,
        "sync_mode": current,
        "sync_mode_notice": notice,
    }
