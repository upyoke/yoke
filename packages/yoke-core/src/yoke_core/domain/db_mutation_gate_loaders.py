"""DB row, capability, and project-flow loaders for the joint gates.

Owns the single-statement database reads consumed by every gate phase:

* :func:`_load_item_row` — item shape needed by every gate.
* :func:`_load_capability_settings` — validated migration_model
  capability settings for the item's project.
* :func:`_resolve_repo_path` — machine-local checkout path used to
  resolve module files and decision records.
* :func:`_other_non_terminal_profiles` — declared profiles on other
  non-terminal items in the same project, used by overlap detection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_mutation_gate_shared import (
    _NON_TERMINAL_STATUSES,
    _safe_parse_dict,
)
from yoke_core.domain.db_mutation_profile import (
    STATE_DECLARED,
    DbMutationProfileError,
    validate as validate_profile,
)
from yoke_core.domain.migration_model_capability import (
    CAPABILITY_TYPE as MIGRATION_MODEL_CAPABILITY_TYPE,
    MigrationModelCapabilityError,
    validate as validate_capability,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_checkout_locations import checkout_for_project


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _load_item_row(conn: Any, item_id: int) -> Optional[Dict[str, Any]]:
    p = _placeholder(conn)
    row = conn.execute(
        "SELECT i.id, i.workflow_id, i.workflow_version_id, i.status, "
        "p.slug AS project, i.project_id, "
        "i.db_mutation_profile, i.db_compatibility_attestation, i.test_results "
        "FROM items i "
        "JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {p}",
        (item_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def _load_capability_settings(
    conn: Any, project: str
) -> Optional[Dict[str, Any]]:
    p = _placeholder(conn)
    project_id = resolve_project_id(conn, project)
    row = conn.execute(
        "SELECT COALESCE(settings, '{}') AS settings "
        f"FROM project_capabilities WHERE project_id={p} AND type={p}",
        (project_id, MIGRATION_MODEL_CAPABILITY_TYPE),
    ).fetchone()
    if row is None:
        return None
    raw = row["settings"] if hasattr(row, "keys") else row[0]
    parsed = _safe_parse_dict(raw)
    if not parsed:
        return None
    try:
        return validate_capability(parsed)
    except MigrationModelCapabilityError:
        return None


def _resolve_repo_path(conn: Any, project: str) -> Optional[Path]:
    return checkout_for_project(conn, project)


def _other_non_terminal_profiles(
    conn: Any, project: str, exclude_item_id: int
) -> List[Dict[str, Any]]:
    p = _placeholder(conn)
    project_id = resolve_project_id(conn, project)
    rows = conn.execute(
        "SELECT id, db_mutation_profile FROM items "
        f"WHERE project_id = {p} AND id <> {p} AND status IN (" +
        ",".join([p] * len(_NON_TERMINAL_STATUSES)) + ")",
        (project_id, exclude_item_id, *sorted(_NON_TERMINAL_STATUSES)),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item_id = row["id"] if hasattr(row, "keys") else row[0]
        raw_profile = row["db_mutation_profile"] if hasattr(row, "keys") else row[1]
        parsed = _safe_parse_dict(raw_profile)
        if parsed.get("state") != STATE_DECLARED:
            continue
        try:
            normalized = validate_profile(parsed)
        except DbMutationProfileError:
            continue
        normalized["__item_id"] = int(item_id)
        out.append(normalized)
    return out


__all__ = [
    "_load_capability_settings",
    "_load_item_row",
    "_other_non_terminal_profiles",
    "_resolve_repo_path",
]
