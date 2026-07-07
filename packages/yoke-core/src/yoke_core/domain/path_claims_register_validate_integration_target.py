"""Registration-time integration-target validation for path claims.

Two concerns this owns:

1. **Default to project trunk** when the CLI caller omitted
   ``--integration-target`` — looks up ``projects.default_branch`` via
   :mod:`yoke_core.domain.projects_trunk`, falling back to
   :data:`yoke_core.domain.projects_trunk.DEFAULT_TRUNK` when the
   project row has no usable value.
2. **Ref validation** — the supplied (or defaulted) target must
   resolve to a current git ref in the project's repo. The cheap check
   is at registration time; without it, a self-referencing target (an
   item branch slug naming itself) silently passes registration and
   only fails later at activation when ``worktree_preflight.run_preflight``
   tries to anchor the boundary — leaving the operator with an
   unrecoverable claim.

Validation skips silently when this machine has no checkout mapping for
the project, or the mapped checkout is not accessible as a git repo
(test fixtures, partial setups, moved checkouts). The strict path runs
only when there is a real repo to check; this keeps the validator useful
for the live operator bug class without breaking in-memory fixtures that
exercise ``register_for_item`` against a schema-only DB.

Errors subclass
:class:`yoke_core.domain.path_claims_register.PathClaimRegistrationError`
so the existing ``except (PathClaimRegistrationError, PathResolveError)``
clause in ``path_claims_dispatch.cmd_register`` catches them without a
second handler. The error message names the unresolved target, the
project id, and the trunk recommendation so the operator sees the fix
in one line.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims_boundary_git import (
    BoundaryCheckError,
    resolve_integration_head,
)
from yoke_core.domain.path_claims_register import PathClaimRegistrationError
from yoke_core.domain.projects_trunk import (
    DEFAULT_TRUNK,
    resolve_trunk_safe,
)
from yoke_core.domain.project_checkout_locations import checkout_for_project_id


class IntegrationTargetUnresolvable(PathClaimRegistrationError):
    """The integration target does not resolve to a current git ref."""


def _row_value(row, column: str):
    if row is None:
        return None
    if hasattr(row, "keys"):
        return row[column]
    return row[0]


def _fetch_project_for_item(
    conn: Any, item_id: int,
) -> Optional[int]:
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT project_id FROM items WHERE id = {p}", (item_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return None
    value = _row_value(row, "project_id")
    if value is None:
        return None
    return int(value) if str(value).strip() else None


def _is_git_repo(repo_path: Optional[str]) -> bool:
    if not repo_path or not os.path.isdir(repo_path):
        return False
    proc = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "--git-dir"],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode == 0


def resolve_and_validate_integration_target(
    conn: Any,
    *,
    item_id: int,
    supplied_target: Optional[str],
) -> str:
    """Return the validated integration target string.

    When ``supplied_target`` is ``None`` or blank, resolves the
    project's trunk branch from ``projects.default_branch`` and falls
    back to :data:`DEFAULT_TRUNK` when no usable value exists. When
    ``supplied_target`` is non-empty, uses it verbatim.

    Always validates that the resulting target resolves to a current
    git ref in this machine's mapped project checkout (via the existing
    :func:`yoke_core.domain.path_claims_boundary_git.resolve_integration_head`
    resolver, which checks ``refs/remotes/origin/<target>`` then
    ``refs/heads/<target>``). Skips silently when the project
    checkout mapping is unavailable or is not a git repo so callers do
    not have to thread an explicit bypass flag through every fixture.

    Raises :class:`IntegrationTargetUnresolvable` when ref validation
    fails against a real repo. The error message names the unresolved
    target, the project id, and the recommended trunk so the operator
    sees the fix on the same line.
    """
    project_id = _fetch_project_for_item(conn, item_id)
    candidate = (supplied_target or "").strip()
    trunk_hint: Optional[str] = None
    if project_id:
        trunk_hint = resolve_trunk_safe(conn, project_id)
    if not candidate:
        candidate = trunk_hint or DEFAULT_TRUNK
    if not project_id:
        return candidate
    checkout = checkout_for_project_id(project_id)
    repo_path = str(checkout) if checkout is not None else None
    if not _is_git_repo(repo_path):
        return candidate
    try:
        resolve_integration_head(repo_path, candidate)
    except BoundaryCheckError as exc:
        recommended = trunk_hint or DEFAULT_TRUNK
        raise IntegrationTargetUnresolvable(
            f"integration target {candidate!r} does not resolve to a git "
            f"ref in project {project_id!r}; tried "
            f"refs/remotes/origin/{candidate} and refs/heads/{candidate}. "
            f"Use {recommended!r} (the project trunk) unless you have a "
            f"specific reason to target a branch."
        ) from exc
    return candidate


__all__ = [
    "IntegrationTargetUnresolvable",
    "resolve_and_validate_integration_target",
]
