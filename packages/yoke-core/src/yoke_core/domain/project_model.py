"""Read-only Project Model projection.

Returns a grouped tree over the already-split project-scoped storage so
operators and agents see "the project model" as one concept instead of
five tables.  This module is pure read — never write, never expose
secret values, never introduce a new storage surface.

Returned shape::

    {
      "project_id": "buzz",
      "identity": {"name": "...", "github_repo": "...",
                   "default_branch": "...", "emoji": "..."},
      "policy":   {"breakage_policy": "founder_cutover" | "compatibility_required"},
      "structure": {"families": {family_name: [entries...], ...}},
      "capabilities": {cap_type: {...settings...}, ...},
      "secrets_metadata": [{"type": "github", "key": "token", "source": "literal"},
                           ...],   # value omitted; metadata only
      "deployment_flows": [{"id": "...", "name": "...", "stages": [...]}, ...],
    }

The projection sorts deterministically by table-natural keys so callers
can diff snapshots between runs.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, query_one, query_rows
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.projects_breakage_policy import resolve_breakage_policy


_IDENTITY_COLUMNS = (
    "id", "slug", "name", "emoji", "default_branch",
    "github_repo", "public_item_prefix",
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _identity(conn: Any, project_id: int) -> Dict[str, Any]:
    cols = ", ".join(_IDENTITY_COLUMNS)
    p = _p(conn)
    row = query_one(
        conn, f"SELECT {cols} FROM projects WHERE id={p}", (project_id,),
    )
    if row is None:
        return {}
    return {col: row[col] for col in _IDENTITY_COLUMNS}


def _structure(conn: Any, project_id: int) -> Dict[str, List[Dict[str, Any]]]:
    p = _p(conn)
    rows = query_rows(
        conn,
        "SELECT family, attachment_value, attachment_kind, entry_key, payload "
        f"FROM project_structure WHERE project_id={p} "
        "ORDER BY family, attachment_value, entry_key",
        (project_id,),
    )
    out: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        family = row["family"]
        try:
            payload = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        entry: Dict[str, Any] = {
            "attachment": row["attachment_value"],
            "payload": payload,
        }
        if row["attachment_kind"]:
            entry["attachment_kind"] = row["attachment_kind"]
        if row["entry_key"]:
            entry["entry_key"] = row["entry_key"]
        out.setdefault(family, []).append(entry)
    return out


def _capabilities(conn: Any, project_id: int) -> Dict[str, Any]:
    p = _p(conn)
    rows = query_rows(
        conn,
        "SELECT type, COALESCE(settings, '{}') AS settings "
        f"FROM project_capabilities WHERE project_id={p} ORDER BY type",
        (project_id,),
    )
    out: Dict[str, Any] = {}
    for row in rows:
        cap_type = row["type"]
        try:
            out[cap_type] = json.loads(row["settings"] or "{}")
        except (TypeError, ValueError):
            out[cap_type] = {}
    return out


def _secrets_metadata(conn: Any, project_id: int) -> List[Dict[str, str]]:
    p = _p(conn)
    rows = query_rows(
        conn,
        "SELECT type, key, source FROM capability_secrets "
        f"WHERE project_id={p} ORDER BY type, key",
        (project_id,),
    )
    return [
        {"type": row["type"], "key": row["key"], "source": row["source"]}
        for row in rows
    ]


def _deployment_flows(conn: Any, project_id: int) -> List[Dict[str, Any]]:
    p = _p(conn)
    rows = query_rows(
        conn,
        "SELECT id, name, COALESCE(stages, '[]') AS stages "
        f"FROM deployment_flows WHERE project_id={p} ORDER BY id",
        (project_id,),
    )
    out: List[Dict[str, Any]] = []
    for row in rows:
        try:
            stages = json.loads(row["stages"] or "[]")
        except (TypeError, ValueError):
            stages = []
        out.append({"id": row["id"], "name": row["name"], "stages": stages})
    return out


def read_project_model(
    project: str, *, db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return the grouped Project Model tree for *project*, or None when
    the project does not exist.

    Pure read.  No secret values are exposed in the returned tree —
    only the (type, key, source) metadata for each entry of
    ``capability_secrets``.
    """
    conn = connect(db_path)
    try:
        ident = resolve_project(conn, project, required=False)
        if ident is None:
            return None
        identity = _identity(conn, ident.id)
        if not identity:
            return None
        try:
            policy = {"breakage_policy": resolve_breakage_policy(conn, ident.slug)}
        except Exception:  # noqa: BLE001
            policy = {"breakage_policy": "founder_cutover"}
        structure = {"families": _structure(conn, ident.id)}
        return {
            "project_id": ident.id,
            "project_slug": ident.slug,
            "identity": identity,
            "policy": policy,
            "structure": structure,
            "capabilities": _capabilities(conn, ident.id),
            "secrets_metadata": _secrets_metadata(conn, ident.id),
            "deployment_flows": _deployment_flows(conn, ident.id),
        }
    finally:
        conn.close()


__all__ = ["read_project_model"]
