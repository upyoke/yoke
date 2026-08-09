"""Persistence and version operations for declarative workflows."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.builtin_workflow_canon import (
    canon_generations,
    recognize,
)
from yoke_core.domain.builtin_workflow_version_convergence import (
    converge_builtin_workflows as _converge_builtin_workflows,
    select_current_builtin_workflow_versions as _select_builtin_versions,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.workflow_definition_codec import (
    WorkflowRegistryError,
    canonical_definition_json,
    decode_definition as _decode_definition,
    definition_digest,
)
from yoke_core.domain.workflow_definition_validation import (
    validate_workflow_definition,
)
from yoke_core.domain.workflow_registry_rows import (
    version_by_id as _version_by_id,
    version_row as _version_row,
    workflow_row as _workflow_row,
)
from yoke_core.domain.workflow_registry_sql import (
    marker as _marker,
    row_dict as _row_dict,
    rows_dict as _rows_dict,
)
from yoke_core.domain.workflow_registry_versions import (
    get_workflow_version,
    set_current_workflow_version,
)


def _insert_version(
    conn: Any,
    *,
    workflow_id: str,
    version: int,
    definition: Mapping[str, Any],
    published_by_actor_id: Optional[int],
    derived_from_canon_version: Optional[int] = None,
) -> dict:
    validate_workflow_definition(definition)
    now = iso8601_now()
    canonical = canonical_definition_json(definition)
    digest = definition_digest(definition)
    marker = _marker(conn)
    conn.execute(
        "INSERT INTO workflow_versions "
        "(workflow_id, version, definition_schema_version, definition_json, "
        "definition_digest, published_at, published_by_actor_id, immutable_at, "
        "derived_from_canon_version) "
        f"VALUES ({', '.join(marker for _ in range(9))})",
        (
            workflow_id,
            version,
            int(definition["schema_version"]),
            canonical,
            digest,
            now,
            published_by_actor_id,
            now,
            derived_from_canon_version,
        ),
    )
    row = _version_row(conn, workflow_id, version)
    if row is None:
        raise WorkflowRegistryError(
            f"workflow version {workflow_id}@{version} was not inserted"
        )
    return row


def converge_builtin_workflows(conn: Any) -> None:
    """Insert missing built-ins without mutating published versions."""
    _converge_builtin_workflows(conn, insert_version=_insert_version)


def select_current_builtin_workflow_versions(conn: Any) -> dict[str, int]:
    """Select code-owned revisions without changing existing item pins."""
    return _select_builtin_versions(conn, insert_version=_insert_version)


def _current_definition(conn: Any, workflow_id: str) -> tuple[dict, dict]:
    workflow = _workflow_row(conn, workflow_id)
    if workflow is None:
        raise WorkflowRegistryError(f"unknown workflow {workflow_id!r}")
    current_id = workflow.get("current_version_id")
    if current_id is None:
        raise WorkflowRegistryError(
            f"workflow {workflow_id!r} has no current version"
        )
    version = _version_by_id(conn, int(current_id))
    if version is None or version["workflow_id"] != workflow_id:
        raise WorkflowRegistryError(
            f"workflow {workflow_id!r} has an invalid current version"
        )
    return workflow, version


def resolve_current_workflow_pin(
    conn: Any,
    workflow_id: str,
) -> tuple[str, int]:
    """Return the active workflow id and immutable current-version row id."""
    workflow, version = _current_definition(conn, workflow_id)
    if workflow["status"] != "active":
        raise WorkflowRegistryError(f"workflow {workflow_id!r} is disabled")
    return workflow_id, int(version["id"])


def _baseline_for_edit_of(current: Mapping[str, Any]) -> Optional[int]:
    """Which published generation an edit of *current* descends from.

    Editing a published generation makes that generation the baseline. Editing
    something already local carries the original baseline forward, so a chain
    of local edits still remembers the last point Yoke and this universe
    agreed — which is exactly what a later three-way merge needs.

    ``None`` means the baseline is genuinely unknown: a local row published
    before this was recorded. Unknown is reported as unknown, never guessed.
    """
    generation = recognize(
        str(current["workflow_id"]), str(current["definition_digest"])
    )
    if generation is not None:
        return generation.canon_version
    baseline = current.get("derived_from_canon_version")
    return None if baseline is None else int(baseline)


def publish_workflow_version(
    conn: Any,
    *,
    workflow_id: str,
    definition: Mapping[str, Any],
    published_by_actor_id: Optional[int] = None,
    expected_current_version: Optional[int] = None,
) -> dict:
    """Validate, append, and select a new immutable workflow version."""
    marker = _marker(conn)
    if db_backend.connection_is_postgres(conn):
        conn.execute(
            f"SELECT id FROM workflows WHERE id = {marker} FOR UPDATE",
            (workflow_id,),
        ).fetchone()
    workflow, current = _current_definition(conn, workflow_id)
    if workflow["status"] != "active":
        raise WorkflowRegistryError(f"workflow {workflow_id!r} is disabled")
    if (
        expected_current_version is not None
        and int(current["version"]) != int(expected_current_version)
    ):
        raise WorkflowRegistryError(
            f"workflow {workflow_id!r} current version changed from "
            f"{expected_current_version} to {current['version']}; refresh first"
        )
    previous = _decode_definition(current["definition_json"])
    validate_workflow_definition(definition, previous=previous)
    cursor = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS maximum "
        f"FROM workflow_versions WHERE workflow_id = {marker}",
        (workflow_id,),
    )
    row = _row_dict(cursor, cursor.fetchone())
    next_version = int(row["maximum"]) + 1
    if definition_digest(definition) == current["definition_digest"]:
        raise WorkflowRegistryError(
            "new workflow version must change the definition"
        )
    published = _insert_version(
        conn,
        workflow_id=workflow_id,
        version=next_version,
        definition=definition,
        published_by_actor_id=published_by_actor_id,
        derived_from_canon_version=_baseline_for_edit_of(current),
    )
    # Publishing here stops this workflow following the published canon, because
    # from now on taking a new generation is a merge against local work rather
    # than a move onto it, and nothing may make that call unattended. The stale
    # adoption notice clears with it: it described a move this edit supersedes.
    conn.execute(
        f"UPDATE workflows SET current_version_id = {marker}, "
        f"canon_follow = 'manual', canon_adopted_from_version = NULL, "
        f"updated_at = {marker} WHERE id = {marker}",
        (int(published["id"]), iso8601_now(), workflow_id),
    )
    conn.commit()
    return {
        "workflow_id": workflow_id,
        "version": next_version,
        "version_id": int(published["id"]),
        "definition_digest": published["definition_digest"],
    }


def _version_provenance(version_row) -> dict:
    """Where a stored version's content came from, as the dashboard shows it.

    A universe's version numbers are its own sequence positions, so the number
    alone says nothing about which published generation a row holds. Matching
    the digest against the canon answers that, and the caller compares
    ``canon_version`` with the local number to see that a universe adopted a
    generation on its own schedule -- normal, and not drift.

    Only built-in workflows have a canon. A workflow authored in this universe
    is local by definition, not by failing to be recognized.
    """
    generation = recognize(
        str(version_row["workflow_id"]), str(version_row["definition_digest"])
    )
    if generation is not None:
        return {"kind": "canon", "canon_version": generation.canon_version}
    baseline = version_row.get("derived_from_canon_version")
    return {
        "kind": "local",
        "derived_from_canon_version": None if baseline is None else int(baseline),
    }


def _workflow_canon_status(version_row: Mapping[str, Any]) -> dict:
    """Where this universe's current definition stands against the canon.

    Four states, along two independent questions: is this definition Yoke's or
    this universe's own, and has Yoke published anything since. A customized
    definition sitting on the newest generation needs nothing; one whose
    baseline has been overtaken needs a merge, not an overwrite, and saying so
    requires the recorded baseline rather than a guess.

    The stored ``follow`` setting and the last automatic adoption ride along,
    because both are facts about this same relationship: a reader deciding what
    to show about an update needs to know whether the next one arrives by
    itself. Neither appears where there is no canon to stand against, since a
    following setting for a workflow nothing publishes describes nothing.
    """
    workflow_id = str(version_row["workflow_id"])
    generations = canon_generations(workflow_id)
    if str(version_row["source"]) != "built_in" or not generations:
        return {"state": "not_applicable"}
    newest = generations[-1]
    adopted_from = version_row.get("canon_adopted_from_version")
    status = {
        "latest_canon_version": newest.canon_version,
        "follow": str(version_row.get("canon_follow") or "auto"),
        "adopted_from_version": (
            None if adopted_from is None else int(adopted_from)
        ),
    }
    current = recognize(workflow_id, str(version_row["definition_digest"]))
    if current is not None:
        status["current_canon_version"] = current.canon_version
        status["state"] = (
            "up_to_date"
            if current.canon_version == newest.canon_version
            else "update_available"
        )
        return status
    baseline = version_row.get("derived_from_canon_version")
    baseline = None if baseline is None else int(baseline)
    status["derived_from_canon_version"] = baseline
    # An unknown baseline reports as plain customization. Claiming an update
    # is available would assert a relationship to the canon that was never
    # recorded, and the whole point of the baseline is to stop guessing it.
    status["state"] = (
        "customized_update_available"
        if baseline is not None and baseline < newest.canon_version
        else "customized"
    )
    return status


def list_current_workflows(conn: Any) -> list[dict]:
    """Return each workflow joined to its selected immutable definition."""
    workflow_cursor = conn.execute(
        "SELECT w.id, w.name, w.description, w.source, w.status, "
        "w.current_version_id, v.version, v.definition_schema_version, "
        "v.definition_json, v.definition_digest, v.published_at, "
        "v.published_by_actor_id, v.immutable_at, "
        "v.derived_from_canon_version, "
        "w.canon_follow, w.canon_adopted_from_version "
        "FROM workflows w "
        "JOIN workflow_versions v ON v.id = w.current_version_id "
        "ORDER BY w.name, w.id"
    )
    rows = _rows_dict(workflow_cursor)
    version_cursor = conn.execute(
        "SELECT id, workflow_id, version, definition_digest, published_at, "
        "published_by_actor_id, immutable_at, derived_from_canon_version "
        "FROM workflow_versions "
        "ORDER BY workflow_id, version"
    )
    version_rows = _rows_dict(version_cursor)
    versions_by_workflow: dict[str, list[dict]] = {}
    for version_row in version_rows:
        versions_by_workflow.setdefault(
            str(version_row["workflow_id"]), []
        ).append({
            "id": int(version_row["id"]),
            "version": int(version_row["version"]),
            "definition_digest": version_row["definition_digest"],
            "published_at": version_row["published_at"],
            "published_by_actor_id": version_row["published_by_actor_id"],
            "immutable_at": version_row["immutable_at"],
            "provenance": _version_provenance(version_row),
        })
    result: list[dict] = []
    for row in rows:
        result.append({
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "source": row["source"],
            "status": row["status"],
            "current_version": int(row["version"]),
            "current_version_id": int(row["current_version_id"]),
            "definition_schema_version": int(
                row["definition_schema_version"]
            ),
            "definition_digest": row["definition_digest"],
            "published_at": row["published_at"],
            "published_by_actor_id": row["published_by_actor_id"],
            "immutable_at": row["immutable_at"],
            "definition": _decode_definition(row["definition_json"]),
            "versions": versions_by_workflow.get(str(row["id"]), []),
            "canon_status": _workflow_canon_status({**row, "workflow_id": row["id"]}),
        })
    return result


__all__ = [
    "WorkflowRegistryError",
    "canonical_definition_json",
    "converge_builtin_workflows",
    "definition_digest",
    "get_workflow_version",
    "list_current_workflows",
    "publish_workflow_version",
    "resolve_current_workflow_pin",
    "select_current_builtin_workflow_versions",
    "set_current_workflow_version",
]
