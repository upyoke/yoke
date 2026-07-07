"""Per-item repo-root resolution for the readiness checks.

Path strings in the File Budget and function-owner refs are project-
relative; the existence checks in ``idea_readiness_check`` resolve them
against this machine's mapped checkout for the item project so external-
project tickets do not silently skip the existence check against the
wrong tree. Lives in a sibling module to keep the parent
``idea_readiness_check.py`` under the 350-line cap.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional

from . import db_backend
from yoke_core.domain.project_checkout_locations import checkout_for_project_id


def _resolve_repo_root() -> Path:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        # The ``git`` binary is unavailable in this execution context
        # (e.g. a function-dispatch environment with a sanitized PATH).
        # Degrade to the filesystem walk-up resolver, then cwd, so
        # readiness resolves the checkout with or without git rather than
        # raising an uncaught FileNotFoundError and crashing the handler.
        return _repo_root_without_git()
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return Path.cwd()


def _repo_root_without_git() -> Path:
    """Resolve the repo root without shelling out to ``git``.

    Walks up the filesystem (from cwd, then this module) for a ``.git``
    marker via the shared resolver, falling back to cwd. Never raises.
    """
    from yoke_core.api.repo_root import find_repo_root

    for start in (Path.cwd(), Path(__file__)):
        try:
            return find_repo_root(start)
        except RuntimeError:
            continue
    return Path.cwd()


def _resolve_repo_root_for_item(
    conn: Optional[Any], item_id: int,
) -> Path:
    # Fall back to the ambient git root when no item context is available
    # (test stubs that monkeypatch _resolve_repo_root rely on this path).
    if conn is None or not item_id:
        return _resolve_repo_root()
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            "SELECT project_id FROM items "
            f"WHERE id = {p}",
            (int(item_id),),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return _resolve_repo_root()
    if not row or not row[0]:
        return _resolve_repo_root()
    candidate = checkout_for_project_id(int(row[0]))
    if candidate is None or not candidate.is_dir():
        return _resolve_repo_root()
    return candidate


__all__ = ["_resolve_repo_root", "_resolve_repo_root_for_item"]
