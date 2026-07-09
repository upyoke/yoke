"""Python owner for epic-task GitHub sync.

Owns shared sync utilities, USAGE constants, and the public wrapper
functions consumed by sibling modules and external callers. The CLI mode
parser lives in ``epic_task_sync_cli`` and is invoked from ``main`` via a
thin lazy delegate.

Sibling modules:
- ``epic_task_sync_github``: per-task GitHub-facing helpers (issues, labels, bodies).
- ``epic_task_sync_github_core``: shared core for ``sync_epic_tasks`` / ``sync_progress_notes``.
- ``epic_task_sync_github_orchestrator``: ``sync_epic_tasks`` orchestration loop.
- ``epic_task_sync_github_backfill``: ``backfill_task_titles`` / ``backfill_task_labels`` helpers.
- ``epic_task_sync_github_create``: GitHub create + dedup helpers used during sync.
- ``epic_task_sync_local``: local-DB-only operations (dispatch chains).
- ``epic_task_sync_cli``: argv mode parser for the operator entry point.

Yoke does NOT use the ``gh`` CLI; every GitHub interaction here goes
through the typed :mod:`yoke_core.domain.github_rest` surface.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, TextIO

from yoke_contracts.project_contract.label_policy import DEFAULT_LABEL_COLORS
from yoke_core.domain import db_backend
from yoke_core.domain.project_github_auth import (
    MissingRepoMetadata,
    resolve_project_github_auth,
)


def _is_dry_run() -> bool:
    return os.environ.get("YOKE_DRY_RUN", "0") == "1"


USAGE_PREFIX = "Usage: python3 -m yoke_core.domain.epic_task_sync"
LABEL_USAGE = f"{USAGE_PREFIX} label <epic-id> <task-num> <new-status>"
BODY_USAGE = f"{USAGE_PREFIX} body <epic-id> <task-num>"
PROGRESS_USAGE = f"{USAGE_PREFIX} progress <epic-ref> [task-id]"
SYNC_USAGE = f"{USAGE_PREFIX} sync <epic-ref> [epic-dir]"
BACKFILL_TITLES_USAGE = f"{USAGE_PREFIX} backfill-titles <epic-ref>"
BACKFILL_LABELS_USAGE = f"{USAGE_PREFIX} backfill-labels <epic-ref>"
# Single-sourced from the shared label contract; these are the get_color
# fallbacks this module's GitHub-label helpers pass.
LABEL_COLOR_DEFAULT = DEFAULT_LABEL_COLORS["label_color_status"]
TYPE_LABEL_COLOR_DEFAULT = DEFAULT_LABEL_COLORS["label_color_type_task"]
WORKTREE_LABEL_COLOR_DEFAULT = DEFAULT_LABEL_COLORS["label_color_worktree"]


def _repo_root() -> Path:
    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__))


def _db_path() -> str:
    """Retained for non-sync compatibility imports; sync code opens via _connect_db."""
    from yoke_core.domain.db_helpers import resolve_db_path

    return resolve_db_path()


def _connect_db() -> Any:
    from yoke_core.domain.db_helpers import connect

    return connect()


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _yoke_root() -> Path:
    try:
        from yoke_core.domain.worktree import resolve_yoke_root

        return Path(
            resolve_yoke_root(yoke_root_env=os.environ.get("YOKE_ROOT") or None)
        )
    except (ImportError, RuntimeError):
        return _repo_root() / ".yoke"


def _resolve_pat(project: str) -> str:
    """Resolve project GitHub App auth via the canonical resolver. Fail-closed.

    Missing project metadata and resolver failures propagate as
    :class:`ProjectGithubAuthError` so sync callers fail closed before
    any GitHub call is made.
    """
    if not project or project == "null":
        raise MissingRepoMetadata(
            project or "unknown",
            "GitHub sync requires an explicit project id",
        )
    resolved = resolve_project_github_auth(project)
    return resolved.token


def _task_context(
    epic_id: str,
    task_num: int,
    *,
    conn: Optional[Any] = None,
) -> Optional[tuple[str, str, str, str]]:
    query = """
        SELECT
          COALESCE(t.github_issue, '') AS github_issue,
          COALESCE(p.slug, '') AS project,
          COALESCE(p.github_repo, '') AS github_repo,
          COALESCE(t.body, '') AS body
        FROM epic_tasks t
        LEFT JOIN items i ON CAST(i.id AS TEXT) = CAST(t.epic_id AS TEXT)
        LEFT JOIN projects p ON p.id = i.project_id
        WHERE t.epic_id = {p} AND t.task_num = {p}
        LIMIT 1
    """.format(p=_placeholder(conn) if conn is not None else "%s")
    owns_conn = conn is None
    if owns_conn:
        try:
            conn = _connect_db()
        except db_backend.operational_error_types():
            return None
    try:
        row = conn.execute(query, (str(epic_id), int(task_num))).fetchone()
    except db_backend.operational_error_types(conn):
        conn.rollback()
        row = None
    finally:
        if owns_conn and conn is not None:
            conn.close()
    if row is None:
        return None
    return (
        str(row[0] or ""),
        str(row[1] or ""),
        str(row[2] or ""),
        str(row[3] or ""),
    )


def _epic_ref_name(
    epic_ref: str,
    *,
    conn: Any,
    stderr: TextIO,
) -> Optional[str]:
    if epic_ref.lower().startswith("yok-") or epic_ref.isdigit():
        normalized = epic_ref.removeprefix("YOK-").removeprefix("yok-").lstrip("0") or "0"
        row = conn.execute(
            f"SELECT COALESCE(CAST(id AS TEXT), '') FROM items WHERE id = {_placeholder(conn)} LIMIT 1",
            (int(normalized),),
        ).fetchone()
        epic_name = str(row[0] or "") if row else ""
        if not epic_name or epic_name == "null":
            print(f"Error: Item {epic_ref} does not exist", file=stderr)
            return None
        return epic_name
    return epic_ref


def _epic_project_repo(
    epic_name: str,
    *,
    conn: Any,
) -> tuple[str, str]:
    try:
        row = conn.execute(
            f"""
            SELECT
              COALESCE(p.slug, '') AS project,
              COALESCE(p.github_repo, '') AS github_repo
            FROM items i
            LEFT JOIN projects p ON p.id = i.project_id
            WHERE CAST(i.id AS TEXT) = CAST({_placeholder(conn)} AS TEXT)
            LIMIT 1
            """,
            (epic_name,),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        conn.rollback()
        row = None
    if row is None:
        return "", ""
    return str(row[0] or ""), str(row[1] or "")


def _epic_parent_item_id(epic_name: str, *, conn: Any) -> str:
    row = conn.execute(
        f"SELECT COALESCE(CAST(id AS TEXT), '') FROM items WHERE CAST(id AS TEXT) = CAST({_placeholder(conn)} AS TEXT) LIMIT 1",
        (epic_name,),
    ).fetchone()
    if row is None:
        return ""
    return str(row[0] or "")


def _resolve_deps(raw: str) -> list[str]:
    if not raw or raw.lower().strip() in ("", "none"):
        return []
    result = []
    for dep in raw.split(","):
        digits = "".join(c for c in dep if c.isdigit())
        if digits:
            num = int(digits)
            result.append(f"{num:03d}")
    return result


def _backfill_title_has_task_num(current_title: str, task_num: str) -> bool:
    return f"] {task_num} " in current_title or current_title.startswith(f"{task_num} ")


# ---------------------------------------------------------------------------
# Backward-compatibility re-exports from child modules
# (functions moved out to reduce file size but still importable from here)
# ---------------------------------------------------------------------------

def _validate_issue_in_repo(
    item_ref: str,
    issue_num: str,
    repo: str,
    *,
    project: str,
    stderr,
) -> bool:
    from yoke_core.domain.epic_task_sync_github import _validate_issue_in_repo as _impl
    return _impl(item_ref, issue_num, repo, project=project, stderr=stderr)


def backfill_task_titles(epic_ref: str, **kwargs) -> int:
    from yoke_core.domain.epic_task_sync_github import backfill_task_titles as _impl
    return _impl(epic_ref, **kwargs)


def backfill_task_labels(epic_ref: str, **kwargs) -> int:
    from yoke_core.domain.epic_task_sync_github import backfill_task_labels as _impl
    return _impl(epic_ref, **kwargs)


def sync_task_label(epic_id: str, task_num: int, new_status: str, **kwargs) -> int:
    from yoke_core.domain.epic_task_sync_github import sync_task_label as _impl
    return _impl(epic_id, task_num, new_status, **kwargs)


def sync_task_body(epic_id: str, task_num: int, **kwargs) -> int:
    from yoke_core.domain.epic_task_sync_github import sync_task_body as _impl
    return _impl(epic_id, task_num, **kwargs)


def sync_progress_notes(epic_ref: str, task_ref=None, **kwargs) -> int:
    from yoke_core.domain.epic_task_sync_github_core import sync_progress_notes as _impl
    return _impl(epic_ref, task_ref, **kwargs)


def sync_epic_tasks(epic_ref: str, epic_dir: str = "", **kwargs) -> int:
    from yoke_core.domain.epic_task_sync_github_core import sync_epic_tasks as _impl
    return _impl(epic_ref, epic_dir, **kwargs)


# ---------------------------------------------------------------------------
# CLI entry point — thin lazy delegate to the CLI sibling.
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    from yoke_core.domain.epic_task_sync_cli import run

    return run(argv)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
