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

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.yok_n_parser import parse_item_id_or_none
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
from yoke_core.domain.project_identity import render_item_ref, resolve_project_id
from yoke_core.domain.project_checkout_locations import checkout_for_project

_ACTING_ITEM_REF: ContextVar[Optional[str]] = ContextVar(
    "yoke_acting_item_ref", default=None
)


class ItemIdRefMismatch(Exception):
    """Caller public ref and requested ``items.id`` name different rows."""


@contextmanager
def acting_item_ref_bound(item_ref: Optional[str]) -> Iterator[None]:
    """Bind the caller's public item ref for the duration of a gate read."""
    value = item_ref.strip() if isinstance(item_ref, str) and item_ref.strip() else None
    token = _ACTING_ITEM_REF.set(value)
    try:
        yield
    finally:
        _ACTING_ITEM_REF.reset(token)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _assert_item_id_matches_ref(
    conn: Any, item_id: int, expected_ref: str, project: str
) -> None:
    """Refuse when *expected_ref* resolves to a different ``items.id``.

    Comparison is by resolved id, not string equality, so a bare project-local
    sequence and the rendered ``PREFIX-N`` form of the same item agree.
    """
    resolved = parse_item_id_or_none(
        expected_ref, project=project, conn=conn, allow_bare_internal=False,
    )
    if resolved is None or int(resolved) != int(item_id):
        raise ItemIdRefMismatch(
            f"acting item ref {expected_ref!r} does not name "
            f"items.id={int(item_id)}"
        )


def _load_item_row(
    conn: Any,
    item_id: int,
    *,
    acting_item_ref: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
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
    loaded = dict(row)
    expected = (
        acting_item_ref
        if acting_item_ref is not None
        else _ACTING_ITEM_REF.get()
    )
    if expected:
        _assert_item_id_matches_ref(
            conn, item_id, expected, str(loaded.get("project") or ""),
        )
    return loaded


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
        normalized["__item_ref"] = render_item_ref(conn, int(item_id))
        out.append(normalized)
    return out


__all__ = [
    "ItemIdRefMismatch",
    "_load_capability_settings",
    "_load_item_row",
    "_other_non_terminal_profiles",
    "_resolve_repo_path",
    "acting_item_ref_bound",
]
