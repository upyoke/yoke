"""Shared constants, DB read helpers, and pure label helpers for GitHub sync.

Contains only helpers that do NOT call typed REST (so they can be imported
by ``backlog_github_sync.py`` without dragging in mock-test patch surfaces).
Functions that call typed REST (``_get_issue_labels``, ``_get_issue_state``,
``_repo_labels``) live in ``backlog_github_label_sync.py`` and consume the
typed surface via the canonical ``_label_rest`` import.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain import project_label_policy
from yoke_core.domain.epic_task_sync import _db_path
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)
from yoke_core.domain.project_identity import (
    DEFAULT_PUBLIC_ITEM_PREFIX,
    item_project_join_select,
    render_item_ref,
)
from yoke_core.domain.yok_n_parser import parse_item_id

# Label color policy is single-sourced in the shared contracts package and
# re-exported here as the canonical read-side hub for the GitHub-sync cluster
# (which imports these bundled with the DB/label helpers below).
from yoke_contracts.project_contract.label_policy import (  # noqa: F401
    BLOCKED_LABEL_COLOR,
    DEFAULT_COLOR_OWNER,
    DEFAULT_COLOR_SOURCE,
    DEFAULT_COLOR_STATUS,
    DEFAULT_COLOR_TYPE_EPIC,
    DEFAULT_COLOR_TYPE_ISSUE,
    DEFAULT_COLOR_WORKTREE,
    FROZEN_LABEL_COLOR,
    REPO_LABEL_DEFINITIONS,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Label category prefixes
LABEL_CATEGORIES = ("status:", "priority:", "type:", "source:", "owner:", "worktree:")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _rollback_quietly(conn: Any) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def _resolve_item_id(item_id: str, *, conn: Any) -> str:
    """Resolve a CLI/API item token to the internal global ``items.id``."""
    return str(parse_item_id(item_id, conn=conn, allow_bare_internal=True))


def _item_ref(item_id: str | int, *, conn: Any) -> str:
    """Render an internal item id as its project-scoped public ref."""
    try:
        return render_item_ref(conn, int(item_id))
    except Exception:
        return f"{DEFAULT_PUBLIC_ITEM_PREFIX}-{item_id}"


def _item_context(
    item_id: str,
    *,
    conn: Any,
) -> Optional[tuple[str, str, str]]:
    """Return (github_issue, project, github_repo) for an item, or None."""
    p = _p(conn)
    try:
        lookup_id = _resolve_item_id(item_id, conn=conn)
    except ValueError:
        return None
    try:
        row = conn.execute(
            f"""
            SELECT COALESCE(i.github_issue, ''), COALESCE(p.slug, ''), COALESCE(p.github_repo, '')
            FROM items i
            LEFT JOIN projects p ON p.id = i.project_id
            WHERE i.id = {p}
            LIMIT 1
            """,
            (lookup_id,),
        ).fetchone()
    except db_backend.database_error_types(conn):
        _rollback_quietly(conn)
        try:
            row = conn.execute(
                "SELECT COALESCE(github_issue, ''), "
                f"'' FROM items WHERE id = {p} LIMIT 1",
                (lookup_id,),
            ).fetchone()
        except db_backend.database_error_types(conn):
            return None
        if row is None:
            return None
        return str(row[0] or ""), str(row[1] or ""), ""
    if row is None:
        return None
    return str(row[0] or ""), str(row[1] or ""), str(row[2] or "")


def _item_fields(
    item_id: str,
    fields: list[str],
    *,
    conn: Any,
) -> Optional[dict[str, str]]:
    """Read multiple fields from the items table. Returns dict or None."""
    cols, needs_project = item_project_join_select(fields, item_alias="i")
    join = "LEFT JOIN projects p ON p.id = i.project_id" if needs_project else ""
    p = _p(conn)
    try:
        lookup_id = _resolve_item_id(item_id, conn=conn)
    except ValueError:
        return None
    try:
        row = conn.execute(
            f"SELECT {cols} FROM items i {join} WHERE i.id = {p} LIMIT 1",  # noqa: S608
            (lookup_id,),
        ).fetchone()
    except db_backend.database_error_types(conn):
        return None
    if row is None:
        return None
    return {f: str(row[i] or "") for i, f in enumerate(fields)}


def _open_conn(conn: Optional[Any]) -> tuple[Any, bool]:
    """Open a connection if needed, returning (conn, owns_conn).

    The active backend facade returns mapping-like rows so downstream consumers
    (``render_body`` in particular) can index rows by column name.
    """
    if conn is not None:
        return conn, False
    return db_backend.connect(), True


def _close_if_owned(conn: Optional[Any], owns: bool) -> None:
    if owns and conn is not None:
        conn.close()


# ---------------------------------------------------------------------------
# GitHub auth availability / env
# ---------------------------------------------------------------------------


def _dry_run() -> bool:
    return os.environ.get("YOKE_DRY_RUN", "0") == "1"


def _github_sync_skip(
    project: str,
    operation: str,
    *,
    conn: Optional[Any] = None,
    out: Optional[Any] = None,
) -> bool:
    """True + one mode-language log line when *project* is backlog-only.

    Shared skip gate for the sync helper family: every sync entrypoint
    calls this (via the ``_bgs()`` accessor) right after resolving the
    project so a ``github_sync_mode=backlog_only`` project short-circuits
    with return code 0 — a logged skip, not an auth error. Callers pass
    their ``conn`` when they hold one so the mode read stays on the same
    authority; helpers without a connection (repo-wide label sync) let
    the resolver open its own.
    """
    import sys as _sys

    from yoke_core.domain.projects_github_sync_mode import (
        github_sync_disabled_notice,
        github_sync_enabled,
    )

    if github_sync_enabled(project, conn=conn):
        return False
    print(github_sync_disabled_notice(project, operation), file=out or _sys.stdout)
    return True


def _github_auth_available(project: str) -> bool:
    """Return True iff ``project`` has resolvable GitHub App auth.

    Replacement gate predicate for the retired ``_gh_available``. Wraps
    :func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`
    in try/except so the gate never raises; auth-resolution failures
    surface as ``False`` and the caller short-circuits without a host
    ``gh`` lookup.
    """
    try:
        resolve_project_github_auth(project)
        return True
    except ProjectGithubAuthError:
        return False
    except Exception:  # pragma: no cover - defensive against config races
        return False


# ---------------------------------------------------------------------------
# Label helpers (read-side)
# ---------------------------------------------------------------------------


def _status_display_label(status: str) -> str:
    """Stored status token IS the GitHub label (no transformation).

    Hyphen-to-space conversion was a cosmetic legacy that broke the resync
    comparator: it pushed `status:refined idea` to GitHub but the comparator
    read the raw label and saw drift against the local `refined-idea`.
    """
    return status


def _label_colors() -> dict[str, str]:
    """Read label colors from project-local policy."""
    return {
        "status": project_label_policy.get_color(
            "label_color_status", DEFAULT_COLOR_STATUS,
        ),
        "type_epic": project_label_policy.get_color(
            "label_color_type_epic", DEFAULT_COLOR_TYPE_EPIC,
        ),
        "type_issue": project_label_policy.get_color(
            "label_color_type_issue", DEFAULT_COLOR_TYPE_ISSUE,
        ),
        "source": project_label_policy.get_color(
            "label_color_source", DEFAULT_COLOR_SOURCE,
        ),
        "owner": project_label_policy.get_color(
            "label_color_owner", DEFAULT_COLOR_OWNER,
        ),
        "worktree": project_label_policy.get_color(
            "label_color_worktree", DEFAULT_COLOR_WORKTREE,
        ),
    }


def _repo_args(repo: str) -> list[str]:
    return ["-R", repo] if repo else []


# _get_issue_labels, _get_issue_state, _repo_labels live in
# backlog_github_label_sync.py because they call the typed REST surface
# via the canonical _label_rest module; this module stays pure-DB so
# the import graph does not pull in the network layer.
