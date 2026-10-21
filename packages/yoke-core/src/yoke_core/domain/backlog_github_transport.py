"""Backlog GitHub transport — GitHub App availability gate + epic sync hook.

Yoke does NOT use the ``gh`` CLI; all GitHub access goes through typed REST
surfaces using bearer tokens returned by
:func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`.
This module hosts the thin ``_dry_run`` env-var gate, the historical
``_github_auth_available`` auth probe name, ``_issue_write_auth`` (the one
auth resolve an issue sync makes), and the ``_sync_task_children`` dispatch
wrapper used by ``sync_item``.
"""

from __future__ import annotations

import os
from typing import Any, Optional, TextIO

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain import epic_task_sync
from yoke_core.domain.project_identity import render_item_ref, unresolved_item_ref
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuth,
    ProjectGithubAuthError,
    repair_command_hint,
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


def _emit_auth_warning(
    public_ref: str,
    op_name: str,
    exc: ProjectGithubAuthError,
    *,
    stderr: TextIO,
) -> None:
    """Surface typed auth diagnostic without silent swallow."""
    print(
        f"Warning: {op_name} skipped for {public_ref} — "
        f"sync_warning={exc.__class__.__name__}: {exc}",
        file=stderr,
    )
    print(f"  Repair: {repair_command_hint(exc, exc.project)}", file=stderr)


def _issue_write_auth(
    project: str,
    public_ref: str,
    op_name: str,
    *,
    stderr: TextIO,
) -> Optional[ProjectGithubAuth]:
    """Resolve the issues-write auth one issue sync uses for every call.

    Write access covers the issue reads too, so the sync resolves once.
    A failure prints its cause — the typed warning with a repair step when
    the resolver names one — and returns None; the caller reports a failed
    sync before any mutation.
    """
    try:
        return resolve_project_github_auth(
            project, required_permissions=GITHUB_ISSUES_WRITE_PERMISSION_LEVELS
        )
    except ProjectGithubAuthError as exc:
        _emit_auth_warning(public_ref, op_name, exc, stderr=stderr)
    except Exception as exc:  # noqa: BLE001 - any resolver failure refuses the sync
        print(
            f"Error: project '{project}' has no usable GitHub App auth for "
            f"{op_name} ({public_ref}): {exc.__class__.__name__}: {exc}",
            file=stderr,
        )
    return None


def _sync_task_children(
    item_id: str,
    *,
    enabled: bool,
    conn: Any,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Sync generated task issues and dispatch chains when enabled."""
    if not enabled:
        return 0
    try:
        public_ref = render_item_ref(conn, int(item_id))
    except Exception:
        public_ref = unresolved_item_ref()
    return epic_task_sync.sync_epic_tasks(
        public_ref,
        conn=conn,
        stdout=stdout,
        stderr=stderr,
    )


__all__ = [
    "_dry_run",
    "_emit_auth_warning",
    "_github_auth_available",
    "_issue_write_auth",
    "_sync_task_children",
]
