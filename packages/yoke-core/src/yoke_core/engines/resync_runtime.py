"""Runtime helpers for the resync engine (bearer-token REST).

GitHub auth is fail-closed: every helper resolves repo + token through
:func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`
and lets :class:`ProjectGithubAuthError` propagate. Yoke does NOT use
the ``gh`` CLI; all GitHub access is bearer-token REST through
:mod:`yoke_core.domain.gh_rest_transport` and the typed surface in
:mod:`yoke_core.domain.github_rest`.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_github_auth import resolve_project_github_auth


def _parent():
    from yoke_core.engines import resync as _resync
    return _resync


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _resolve_yoke_root() -> str:
    """Return the ``yoke/`` state directory path."""
    env = os.environ.get("YOKE_ROOT")
    if env:
        return _parent().resolve_worktree_yoke_root(yoke_root_env=env)

    try:
        return _parent().resolve_worktree_yoke_root()
    except Exception:
        pass

    from yoke_core.api.repo_root import find_repo_root

    repo_root = find_repo_root(Path(__file__))
    candidate = repo_root / "runtime"
    if candidate.is_dir():
        return str(candidate)

    raise FileNotFoundError("Cannot locate yoke/ state directory.")


def _is_dry_run() -> bool:
    return os.environ.get("YOKE_DRY_RUN", "0") == "1"


def _query_item_status(item_id: str) -> Optional[str]:
    """Look up an item's local status via the DB helpers."""
    try:
        conn = connect()
    except Exception:
        return None
    try:
        p = _p(conn)
        row = conn.execute(
            f"SELECT status FROM items WHERE CAST(id AS TEXT) = CAST({p} AS TEXT) LIMIT 1",
            (item_id,),
        ).fetchone()
        if not row:
            return None
        return row[0]
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _call_domain_sync(func, *args, project: str = "yoke", **kwargs) -> bool:
    """Invoke a :mod:`yoke_core.domain.backlog_github_sync` function in-process.

    Resolve auth up front so a missing binding remains a typed failure. Domain
    helpers resolve their own request-scoped token; process-global environment
    mutation would let concurrent project syncs observe each other's token.
    """
    resolve_project_github_auth(project)
    stderr = io.StringIO()
    try:
        rc = func(*args, stdout=io.StringIO(), stderr=stderr, **kwargs)
        if rc == 0:
            return True
        _print_domain_sync_reason(func, stderr.getvalue(), f"exit code {rc}")
        return False
    except Exception as exc:
        _print_domain_sync_reason(
            func, stderr.getvalue(), f"{type(exc).__name__}: {exc}",
        )
        return False


def _print_domain_sync_reason(func, stderr_text: str, fallback: str) -> None:
    """Forward the reason a domain sync failed instead of hiding it."""
    detail = (stderr_text or "").strip() or fallback
    name = getattr(func, "__name__", "domain sync")
    print(f"  reason: {name} failed: {detail}", file=sys.stderr)
