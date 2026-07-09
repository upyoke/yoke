"""Backlog GitHub transport — GitHub App availability gate + epic sync hook.

Yoke does NOT use the ``gh`` CLI; all GitHub access goes through typed REST
surfaces using bearer tokens returned by
:func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`.
This module hosts the thin ``_dry_run`` env-var gate, the historical
``_github_auth_available`` auth probe name, and the ``_sync_epic_children`` dispatch
wrapper used by ``sync_item``.
"""

from __future__ import annotations

import os
from typing import Any, TextIO

from yoke_core.domain import epic_task_sync
from yoke_core.domain.project_identity import DEFAULT_PUBLIC_ITEM_PREFIX, render_item_ref
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)


def _dry_run() -> bool:
    return os.environ.get("YOKE_DRY_RUN", "0") == "1"


def _github_auth_available(project: str) -> bool:
    """Return True iff the project has resolvable GitHub App auth.

    Wraps :func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`
    so the gate never raises; auth-resolution failures surface as
    ``False`` and the caller short-circuits.
    """
    try:
        resolve_project_github_auth(project)
        return True
    except ProjectGithubAuthError:
        return False
    except Exception:  # pragma: no cover - defensive against config races
        return False


def _sync_epic_children(
    item_id: str,
    *,
    item_type: str,
    conn: Any,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Sync epic child task issues and dispatch chains when the item is an epic."""
    if item_type != "epic":
        return 0
    try:
        item_ref = render_item_ref(conn, int(item_id))
    except Exception:
        item_ref = f"{DEFAULT_PUBLIC_ITEM_PREFIX}-{item_id}"
    return epic_task_sync.sync_epic_tasks(
        item_ref,
        conn=conn,
        stdout=stdout,
        stderr=stderr,
    )


__all__ = [
    "_dry_run",
    "_github_auth_available",
    "_sync_epic_children",
]
