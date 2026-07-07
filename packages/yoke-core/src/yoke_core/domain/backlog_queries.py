"""Backlog query and read operations, plus shared helpers.

This module contains read-only backlog operations (get, list, search)
and shared helper functions used by sibling modules ``backlog_updates``
and ``backlog_rendering``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import db_backend
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_identity import resolve_project


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

VALID_STRUCTURED_FIELDS = frozenset({
    "spec", "design_spec", "technical_plan", "worktree_plan",
    "shepherd_log", "shepherd_caveats", "test_results", "deploy_log",
    "browser_qa_metadata",
    "db_mutation_profile", "db_compatibility_attestation",
    "architecture_impact",
})

# Content fields that track spec_updated_at/spec_updated_by
CONTENT_TRACKING_FIELDS = frozenset({
    "spec", "design_spec", "technical_plan", "worktree_plan",
    "db_mutation_profile", "db_compatibility_attestation",
})

INTEGER_FIELDS = frozenset({"rework_count", "frozen", "id"})

LABEL_SYNC_FIELDS = frozenset({
    "status", "priority", "type", "worktree", "source", "owner",
})


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _yoke_root() -> Path:
    """Return the canonical ``yoke/`` state dir on the main repo.

    Delegates to :func:`yoke_core.domain.worktree.resolve_yoke_root` so
    linked-worktree cwd contexts strip back to the main repo instead of
    silently resolving to ``.worktrees/<branch>/yoke``.

    The canonical worktree resolver requires a git-aware cwd or
    ``CLAUDE_PROJECT_DIR``. In test contexts (pytest tmp paths, fixtures
    that chdir into non-git directories) neither is available; fall back
    to the shared repo-root resolver in that case so config reads and
    backlog-dir resolution still work. The write-path fail-loud guard
    (``_assert_write_db_ready``) catches the case where a stale fallback
    DB location would otherwise be bootstrapped silently.
    """
    try:
        from yoke_core.domain.worktree import resolve_yoke_root
        return Path(resolve_yoke_root())
    except (RuntimeError, ImportError):
        from yoke_core.api.repo_root import find_repo_root

        return find_repo_root(Path(__file__)) / "runtime"


def _resolve_write_db_path() -> str:
    """Return the retired DB path token for legacy write call signatures."""
    return ""


def _assert_write_db_ready(db_path: str) -> None:
    """Legacy guard slot; Postgres authority is resolved by ``connect()``."""
    return


# ---------------------------------------------------------------------------
# Shared utility helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _zero_pad(n: int) -> str:
    if n < 10:
        return f"00{n}"
    elif n < 100:
        return f"0{n}"
    return str(n)


def _is_dry_run() -> bool:
    return os.environ.get("YOKE_DRY_RUN", "0") == "1"


def _normalize_item_ref(raw: Optional[str]) -> Optional[str]:
    """Canonicalize item-like refs to ``YOK-N`` while preserving free text."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    candidate = text
    if text.upper().startswith("YOK-"):
        candidate = text[4:]
    if candidate.isdigit():
        return f"YOK-{int(candidate)}"
    return text


# ---------------------------------------------------------------------------
# DB read helpers
# ---------------------------------------------------------------------------

def _resolve_deploy_envs(conn: Any, project: str) -> list[str]:
    """Resolve valid deployment environments for a project.

    Returns a list of env names, or empty list if none found.
    """
    envs: set[str] = set()
    ident = resolve_project(conn, project, required=False)
    if ident is None:
        return []

    # Check environments + sites tables
    try:
        rows = conn.execute(
            """SELECT DISTINCT e.name AS env_name
               FROM environments e JOIN sites s ON s.id = e.site
               WHERE s.project_id = %s""",
            (ident.id,),
        ).fetchall()
        for r in rows:
            val = r["env_name"] if hasattr(r, "keys") and "env_name" in r.keys() else r[0]
            if val:
                envs.add(val)
    except db_backend.operational_error_types(conn):
        pass  # tables don't exist

    # Check deployment_flows.target_env
    try:
        rows = conn.execute(
            """SELECT DISTINCT target_env AS env_name
               FROM deployment_flows
               WHERE project_id = %s AND target_env IS NOT NULL AND target_env <> ''""",
            (ident.id,),
        ).fetchall()
        for r in rows:
            val = r["env_name"] if hasattr(r, "keys") and "env_name" in r.keys() else r[0]
            if val:
                envs.add(val)
    except db_backend.operational_error_types(conn):
        pass

    if envs:
        return sorted(envs)

    # Fallback: project_capabilities
    try:
        cap_row = conn.execute(
            "SELECT COALESCE(settings, '{}') AS config FROM project_capabilities "
            "WHERE project_id = %s AND type = 'deployment_environments'",
            (ident.id,),
        ).fetchone()
        if cap_row:
            import json as _json
            config_val = cap_row["config"] if hasattr(cap_row, "keys") and "config" in cap_row.keys() else cap_row[0]
            env_config = _json.loads(config_val)
            cap_envs = env_config.get("environments", [])
            if cap_envs:
                return sorted(cap_envs)
    except Exception:
        pass

    return []


def _get_next_id(conn: Any) -> int:
    """Get the next available item ID."""
    row = conn.execute(
        "SELECT COALESCE(MAX(id), 0) + 1 FROM items"
    ).fetchone()
    return row[0]


def _query_item_field(
    conn: Any,
    item_id: int,
    field: str,
) -> Any:
    """Read a single field value for an item."""
    row = conn.execute(
        f"SELECT {field} FROM items WHERE id = %s",
        (item_id,),
    ).fetchone()
    return row[0] if row else None


def get_next_display_id(db_path: Optional[str] = None) -> str:
    """Return the next available backlog item display ID."""
    if db_path is None:
        db_path = _resolve_write_db_path()
    _assert_write_db_ready(db_path)
    conn = connect(db_path)
    try:
        return f"YOK-{_get_next_id(conn)}"
    finally:
        conn.close()


def dedup_search(
    keywords: str, project: Optional[str] = None
) -> list[dict[str, Any]]:
    """Search item titles and structured content for duplicate-like keyword matches.

    searches title plus structured fields directly instead of the
    retired ``items.body`` cache column. When ``project`` is given (a slug
    or stringified id), results are scoped to that project — the default
    for ``yoke items search`` from a project checkout; ``None`` searches
    every project (the operator-debug global shape).
    """
    db_path = _resolve_write_db_path()
    _assert_write_db_ready(db_path)
    conn = connect(db_path)
    try:
        # Operator-input search: pre-lower the pattern and wrap each
        # column in LOWER(...) for explicit case-insensitive matching.
        pattern = f"%{keywords.lower()}%"
        where = (
            "WHERE (LOWER(title) LIKE %s OR LOWER(spec) LIKE %s "
            "OR LOWER(design_spec) LIKE %s OR LOWER(technical_plan) LIKE %s)"
        )
        params: list[Any] = [pattern, pattern, pattern, pattern]
        if project is not None:
            ident = resolve_project(conn, project, required=False)
            if ident is None:
                return []
            where += " AND project_id = %s"
            params.append(ident.id)
        rows = conn.execute(
            f"SELECT id, title, status FROM items {where} ORDER BY id",
            tuple(params),
        ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "title": row["title"],
                "status": row["status"],
            }
            for row in rows
        ]
    finally:
        conn.close()
