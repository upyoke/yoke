"""Reader for ``projects.github_sync_mode`` — the per-project GitHub sync switch.

``github_sync_mode`` is a project-wide stance on whether the backlog
mirrors to GitHub issues at all.

Allowed values::

    enabled       = backlog items/epic tasks mirror to GitHub issues through
                    the sync helper family; setting it requires an active,
                    verified GitHub App repository binding
    backlog_only  = the backlog lives ONLY in the Yoke DB; every GitHub
                    issue sync surface (create/update/close/comment/label,
                    resync detect+repair) skips or refuses for the project

``backlog_only`` exists so a project can keep a ``github_repo`` binding
for code delivery (pushes, CI, deploys) while never mirroring backlog
content to that repo's issue tracker. Flipping a project's
``github_repo`` to a different repo MUST be preceded by flipping this
switch to ``backlog_only`` when the backlog is not meant to appear in
the new repo — otherwise the first sync after the flip would mass-create
the backlog as issues there (see ``.yoke/docs/github-sync.md``).

New projects default to ``backlog_only``. The column is added by the
idempotent schema-init migrations. This reader tolerates a pre-migration
schema (column absent) and legacy NULL/empty values — both resolve to
``enabled`` until the explicit sync-mode repair normalizes unbound rows.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.project_contract.github_sync_mode import (  # noqa: F401
    GITHUB_SYNC_BACKLOG_ONLY,
    GITHUB_SYNC_ENABLED,
    VALID_GITHUB_SYNC_MODES,
)
from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.schema_common import _column_exists as _schema_column_exists


GITHUB_SYNC_MODE_COLUMN = "github_sync_mode"


class GithubSyncModeError(ValueError):
    """Raised when a ``github_sync_mode`` value is not in the vocabulary."""


def validate_github_sync_mode(value: Any) -> str:
    """Return *value* as a canonical mode string or raise typed error."""
    cleaned = str(value or "").strip()
    if cleaned not in VALID_GITHUB_SYNC_MODES:
        raise GithubSyncModeError(
            f"github_sync_mode must be one of "
            f"{sorted(VALID_GITHUB_SYNC_MODES)}, got {value!r}"
        )
    return cleaned


def validate_github_sync_mode_update(
    value: Any,
    *,
    conn: Any,
    project_id: int,
) -> str:
    """Validate a mode write and reject enabling unusable GitHub state."""
    selected = validate_github_sync_mode(value)
    if selected != GITHUB_SYNC_ENABLED:
        return selected
    from yoke_core.domain.project_github_binding_active import (
        project_has_active_verified_github_binding,
    )

    if not project_has_active_verified_github_binding(conn, project_id):
        raise GithubSyncModeError(
            "github_sync_mode=enabled requires an active, verified GitHub App "
            "repository binding; bind the repository successfully before "
            "enabling issue sync"
        )
    return selected


def resolve_github_sync_mode(project: str, *, conn: Optional[Any] = None) -> str:
    """Return the GitHub sync mode for *project*.

    Reads ``projects.github_sync_mode`` when the column exists and the
    project row has a non-null value. Falls back to ``enabled`` when the
    column is absent, the row is missing, or the value is NULL/empty —
    pre-switch installs keep syncing exactly as before.

    Raises :class:`GithubSyncModeError` when the column exists but the
    stored value is outside :data:`VALID_GITHUB_SYNC_MODES`.
    """
    owns_conn = conn is None
    if owns_conn:
        from yoke_core.domain.db_helpers import connect

        try:
            conn = connect()
        except (FileNotFoundError,) + db_backend.operational_error_types():
            return GITHUB_SYNC_ENABLED
    try:
        if not _schema_column_exists(conn, "projects", GITHUB_SYNC_MODE_COLUMN):
            return GITHUB_SYNC_ENABLED
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        try:
            ident = resolve_project(conn, project, required=False)
        except db_backend.operational_error_types(conn):
            _rollback_quietly(conn)
            return GITHUB_SYNC_ENABLED
        if ident is None:
            return GITHUB_SYNC_ENABLED
        try:
            row = conn.execute(
                f"SELECT {GITHUB_SYNC_MODE_COLUMN} FROM projects WHERE id = {p}",
                (ident.id,),
            ).fetchone()
        except db_backend.operational_error_types(conn):
            _rollback_quietly(conn)
            return GITHUB_SYNC_ENABLED
        if row is None:
            return GITHUB_SYNC_ENABLED
        value = row[GITHUB_SYNC_MODE_COLUMN] if hasattr(row, "keys") else row[0]
        if not value:
            return GITHUB_SYNC_ENABLED
        return validate_github_sync_mode(value)
    finally:
        if owns_conn and conn is not None:
            conn.close()


def github_sync_enabled(project: str, *, conn: Optional[Any] = None) -> bool:
    """True when GitHub issue sync is on for *project*."""
    return resolve_github_sync_mode(project, conn=conn) == GITHUB_SYNC_ENABLED


def github_sync_disabled_notice(project: str, operation: str) -> str:
    """One canonical mode-language line for skip logs and refusals."""
    return (
        f"GitHub {operation} skipped for project '{project}': "
        f"{GITHUB_SYNC_MODE_COLUMN}={GITHUB_SYNC_BACKLOG_ONLY} "
        f"(backlog is DB-only; no GitHub issue sync)"
    )


def _rollback_quietly(conn: Any) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


__all__ = [
    "GITHUB_SYNC_BACKLOG_ONLY",
    "GITHUB_SYNC_ENABLED",
    "GITHUB_SYNC_MODE_COLUMN",
    "GithubSyncModeError",
    "VALID_GITHUB_SYNC_MODES",
    "github_sync_disabled_notice",
    "github_sync_enabled",
    "resolve_github_sync_mode",
    "validate_github_sync_mode",
    "validate_github_sync_mode_update",
]
