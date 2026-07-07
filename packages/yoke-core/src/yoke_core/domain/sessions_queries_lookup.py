"""Read-only session and claim lookup surfaces."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional


from . import db_backend
from .harness_capability_registry import downstream_paths_for_manifest
from .sessions_queries_base import _row_to_dict, normalize_claim_item_id


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def list_harness_sessions(
    conn: Any,
    *,
    lane: Optional[str] = None,
    mode: Optional[str] = None,
    workspace: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List active (non-ended) sessions with optional filters."""
    clauses = ["ended_at IS NULL"]
    params: List[Any] = []

    if lane is not None:
        clauses.append(f"execution_lane = {_p(conn)}")
        params.append(lane)
    if mode is not None:
        clauses.append(f"mode = {_p(conn)}")
        params.append(mode)
    if workspace is not None:
        clauses.append(f"workspace = {_p(conn)}")
        params.append(workspace)

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT * FROM harness_sessions WHERE {where} ORDER BY offered_at DESC",
        params,
    ).fetchall()

    result = []
    for r in rows:
        d = _row_to_dict(r)
        if d.get("capabilities"):
            try:
                d["capabilities"] = json.loads(d["capabilities"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def list_claims_for_session(
    conn: Any,
    session_id: str,
    active_only: bool = True,
) -> List[Dict[str, Any]]:
    """List claims for a session, optionally filtering to active only."""
    if active_only:
        rows = conn.execute(
            "SELECT * FROM work_claims "
            f"WHERE session_id = {_p(conn)} AND released_at IS NULL "
            "ORDER BY claimed_at DESC",
            (session_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM work_claims WHERE session_id = {_p(conn)} "
            "ORDER BY claimed_at DESC",
            (session_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_claim_for_work_unit(
    conn: Any,
    *,
    item_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Look up who currently claims a given work unit (item-scoped).

    Returns None if unclaimed, if ``item_id`` is missing, or if the
    requested id is not numeric (process / epic-task targets are looked
    up via their own typed surfaces).
    """
    if not item_id:
        return None
    normalized = normalize_claim_item_id(item_id)
    if not normalized.isdigit():
        return None
    row = conn.execute(
        "SELECT * FROM work_claims "
        f"WHERE target_kind='item' AND item_id = {_p(conn)} AND released_at IS NULL "
        "ORDER BY claimed_at DESC LIMIT 1",
        (int(normalized),),
    ).fetchone()
    return _row_to_dict(row) if row else None


# ---------------------------------------------------------------------------
# Core-derived harness capability lookup
# ---------------------------------------------------------------------------


def resolve_harness_capabilities(
    executor: str,
    workspace: str,
) -> Dict[str, Any]:
    """Derive harness capabilities from shared registry plus manifest limits.

    Surface-specific executor values still belong to a coarse harness family
    for manifest lookup:

    - ``codex-*`` -> ``runtime/harness/codex/manifest.json``
    - ``claude-*`` -> ``runtime/harness/claude-code/manifest.json``

    Unknown executors continue to probe ``runtime/harness/{executor}/``. When a
    manifest exists, command/path truth comes from the shared Yoke registry and
    the manifest can only subtract support through explicit limitations.
    """
    from runtime.harness.hook_helpers_identity import canonical_harness_id

    try:
        manifest_executor = canonical_harness_id(executor)
    except ValueError:
        manifest_executor = executor

    manifest_path = os.path.join(
        workspace,
        "runtime",
        "harness",
        manifest_executor,
        "manifest.json",
    )
    result: Dict[str, Any] = {
        "executor": executor,
        "manifest_executor": manifest_executor,
        "downstream_paths": [],
        "source": "shared_registry",
    }
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
        if not isinstance(manifest, dict):
            raise ValueError("manifest root must be an object")
        result["downstream_paths"] = downstream_paths_for_manifest(manifest)
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        result["source"] = "empty_fallback"

    return result
