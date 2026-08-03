"""Converge immutable built-in workflow history and code-owned revisions."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definitions,
    builtin_workflow_version_history,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.workflow_definition_codec import (
    WorkflowRegistryError,
    canonical_definition_json,
    decode_definition,
    definition_digest,
)
from yoke_core.domain.workflow_definition_validation import (
    validate_workflow_definition,
)
from yoke_core.domain.workflow_registry_rows import (
    version_by_id,
    version_row,
    workflow_row,
)
from yoke_core.domain.builtin_workflow_version_compat import (
    _comparable_form,
    _rewrite_version_to_canonical,
)
from yoke_core.domain.workflow_registry_sql import marker, row_dict, rows_dict

InsertVersion = Callable[..., dict]

# Exact alternate code-owned digests accepted in the fixed version-one slot.
# Requiring a self-consistent canonical payload keeps that supported database
# shape bootable without treating arbitrary definition drift as history.
_COMPATIBLE_CURRENT_AT_VERSION_ONE_DIGESTS = {
    "issue": "3daf973869d819ad3efee5869c9be1f4a71bd28711c919f7fda9c3a7c6d523ad",
    "epic": "7e15484395d46766c933e27ccc29a6d8af2a6a5cf44f85e9b8e0067cdf03ed36",
    "blitz": "dd75d375706225bc131120fe1839179477ae492d8c16f284d8d1c44cd0c6dcce",
    "dash": "30ec3957c785b7748ba2a76ab8f34c4a5d73a166bf6c7fa34d1cca2cb594d369",
}


def _locked_workflow_row(conn: Any, workflow_id: str) -> Optional[dict]:
    """Read one workflow, locking it first on PostgreSQL."""
    if not db_backend.connection_is_postgres(conn):
        return workflow_row(conn, workflow_id)
    bind = marker(conn)
    cursor = conn.execute(
        f"SELECT * FROM workflows WHERE id = {bind} FOR UPDATE",
        (workflow_id,),
    )
    return row_dict(cursor, cursor.fetchone())


def _matches_compatible_current_at_version_one(
    existing: Mapping[str, Any],
    *,
    workflow_id: str,
    version: int,
) -> bool:
    if version != 1:
        return False
    accepted_digest = _COMPATIBLE_CURRENT_AT_VERSION_ONE_DIGESTS.get(workflow_id)
    if accepted_digest is None or str(existing["definition_digest"]) != accepted_digest:
        return False
    try:
        decoded = decode_definition(existing["definition_json"])
    except WorkflowRegistryError:
        return False
    return (
        definition_digest(decoded) == str(existing["definition_digest"])
        and canonical_definition_json(decoded) == str(existing["definition_json"])
    )


def _converge_fixed_version(
    conn: Any,
    fixture: Mapping[str, Any],
    insert_version: InsertVersion,
) -> dict:
    workflow_id = str(fixture["workflow"]["id"])
    version = int(fixture["version"])
    definition = fixture["definition"]
    validate_workflow_definition(definition)
    existing = version_row(conn, workflow_id, version)
    if existing is None:
        return insert_version(
            conn,
            workflow_id=workflow_id,
            version=version,
            definition=definition,
            published_by_actor_id=None,
        )
    if (
        str(existing["definition_digest"]) == definition_digest(definition)
        and str(existing["definition_json"]) == canonical_definition_json(definition)
    ) or _matches_compatible_current_at_version_one(
        existing,
        workflow_id=workflow_id,
        version=version,
    ):
        return existing
    try:
        stored = decode_definition(existing["definition_json"])
    except WorkflowRegistryError:
        stored = None
    if stored is not None and canonical_definition_json(
        _comparable_form(stored)
    ) == canonical_definition_json(_comparable_form(definition)):
        return _rewrite_version_to_canonical(conn, existing, definition)
    raise WorkflowRegistryError(
        f"published built-in {workflow_id}@{version} differs from "
        "the code-owned definition"
    )


def _matching_version(
    conn: Any,
    workflow_id: str,
    definition: Mapping[str, Any],
) -> Optional[dict]:
    bind = marker(conn)
    cursor = conn.execute(
        "SELECT * FROM workflow_versions "
        f"WHERE workflow_id = {bind} AND definition_digest = {bind} "
        "ORDER BY version",
        (workflow_id, definition_digest(definition)),
    )
    canonical = canonical_definition_json(definition)
    for row in rows_dict(cursor):
        if row["definition_json"] == canonical:
            return row
    return None


def _semantically_matching_version(
    conn: Any,
    workflow_id: str,
    definition: Mapping[str, Any],
) -> Optional[dict]:
    """Row whose decoded content equals *definition* modulo compat forms."""
    bind = marker(conn)
    cursor = conn.execute(
        "SELECT * FROM workflow_versions "
        f"WHERE workflow_id = {bind} ORDER BY version",
        (workflow_id,),
    )
    target = canonical_definition_json(_comparable_form(definition))
    for row in rows_dict(cursor):
        try:
            stored = decode_definition(row["definition_json"])
        except WorkflowRegistryError:
            continue
        if canonical_definition_json(_comparable_form(stored)) == target:
            return row
    return None


def _ensure_current_version(
    conn: Any,
    fixture: Mapping[str, Any],
    insert_version: InsertVersion,
) -> dict:
    workflow_id = str(fixture["workflow"]["id"])
    definition = fixture["definition"]
    validate_workflow_definition(definition)
    existing = _matching_version(conn, workflow_id, definition)
    if existing is not None:
        return existing
    drifted = _semantically_matching_version(conn, workflow_id, definition)
    if drifted is not None:
        return _rewrite_version_to_canonical(conn, drifted, definition)
    bind = marker(conn)
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM workflow_versions "
        f"WHERE workflow_id = {bind}",
        (workflow_id,),
    ).fetchone()
    return insert_version(
        conn,
        workflow_id=workflow_id,
        version=int(row[0]) + 1,
        definition=definition,
        published_by_actor_id=None,
    )


def converge_builtin_workflows(
    conn: Any,
    *,
    insert_version: InsertVersion,
) -> None:
    """Append missing revisions while preserving existing current pointers."""
    now = iso8601_now()
    bind = marker(conn)
    histories: dict[str, list[dict]] = {}
    for fixture in builtin_workflow_version_history():
        workflow_id = str(fixture["workflow"]["id"])
        histories.setdefault(workflow_id, []).append(fixture)
    for current_fixture in builtin_workflow_definitions():
        workflow = current_fixture["workflow"]
        workflow_id = str(workflow["id"])
        existing_workflow = _locked_workflow_row(conn, workflow_id)
        if existing_workflow is None:
            conn.execute(
                "INSERT INTO workflows "
                "(id, name, description, source, status, current_version_id, "
                "created_at, updated_at) "
                f"VALUES ({bind}, {bind}, {bind}, {bind}, "
                f"'active', NULL, {bind}, {bind})",
                (
                    workflow_id,
                    workflow["name"],
                    workflow["description"],
                    workflow["source"],
                    now,
                    now,
                ),
            )
        elif existing_workflow["source"] != "built_in":
            raise WorkflowRegistryError(
                f"built-in workflow id {workflow_id!r} is owned by "
                f"{existing_workflow['source']!r}"
            )
        else:
            conn.execute(
                f"UPDATE workflows SET name = {bind}, "
                f"description = {bind}, updated_at = {bind} "
                f"WHERE id = {bind}",
                (
                    workflow["name"],
                    workflow["description"],
                    now,
                    workflow_id,
                ),
            )

        for fixture in histories[workflow_id]:
            _converge_fixed_version(conn, fixture, insert_version)
        desired = _ensure_current_version(conn, current_fixture, insert_version)
        current = workflow_row(conn, workflow_id)
        if current is None:
            raise WorkflowRegistryError(f"workflow {workflow_id!r} is missing")
        current_id = current.get("current_version_id")
        if current_id is None:
            conn.execute(
                f"UPDATE workflows SET current_version_id = {bind}, "
                f"updated_at = {bind} WHERE id = {bind}",
                (int(desired["id"]), now, workflow_id),
            )
        else:
            selected = version_by_id(conn, int(current_id))
            if selected is None or selected["workflow_id"] != workflow_id:
                raise WorkflowRegistryError(
                    f"workflow {workflow_id!r} has an invalid current version"
                )
    conn.commit()


def select_current_builtin_workflow_versions(
    conn: Any,
    *,
    insert_version: InsertVersion,
) -> dict[str, int]:
    """Select code-owned revisions without changing existing item pins."""
    selected: dict[str, int] = {}
    bind = marker(conn)
    for fixture in builtin_workflow_definitions():
        workflow_id = str(fixture["workflow"]["id"])
        workflow = _locked_workflow_row(conn, workflow_id)
        if workflow is None:
            raise WorkflowRegistryError(f"workflow {workflow_id!r} is missing")
        if workflow["source"] != "built_in":
            raise WorkflowRegistryError(
                f"built-in workflow id {workflow_id!r} is owned by "
                f"{workflow['source']!r}"
            )
        target = _ensure_current_version(conn, fixture, insert_version)
        conn.execute(
            f"UPDATE workflows SET current_version_id = {bind}, "
            f"updated_at = {bind} WHERE id = {bind}",
            (int(target["id"]), iso8601_now(), workflow_id),
        )
        selected[workflow_id] = int(target["version"])
    return selected


__all__ = [
    "converge_builtin_workflows",
    "select_current_builtin_workflow_versions",
]
