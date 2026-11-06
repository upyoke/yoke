# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
    builtin_workflow_version_history,
)

from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)

from yoke_core.domain.workflow_registry import (
    converge_builtin_workflows,
    publish_workflow_version,
)

_TS = "2026-07-25T00:00:00Z"


def _seed_generation(conn, workflow_id: str, canon_version: int) -> int:
    """Stand one workflow up holding exactly one published generation."""
    conn.execute("TRUNCATE workflows, workflow_versions RESTART IDENTITY CASCADE")
    fixture = [
        entry
        for entry in builtin_workflow_version_history()
        if entry["workflow"]["id"] == workflow_id
        and int(entry["canon_version"]) == canon_version
    ][0]
    workflow, definition = fixture["workflow"], fixture["definition"]
    conn.execute(
        "INSERT INTO workflows "
        "(id, name, description, source, status, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, 'active', %s, %s)",
        (
            workflow["id"],
            workflow["name"],
            workflow["description"],
            workflow["source"],
            _TS,
            _TS,
        ),
    )
    version_id = conn.execute(
        "INSERT INTO workflow_versions "
        "(workflow_id, version, definition_schema_version, definition_json, "
        "definition_digest, published_at, immutable_at) "
        "VALUES (%s, 1, 1, %s, %s, %s, %s) RETURNING id",
        (
            workflow_id,
            canonical_definition_json(definition),
            definition_digest(definition),
            _TS,
            _TS,
        ),
    ).fetchone()[0]
    conn.execute(
        "UPDATE workflows SET current_version_id = %s WHERE id = %s",
        (version_id, workflow_id),
    )
    conn.commit()
    return int(version_id)


def _state(conn, workflow_id: str) -> dict:
    row = conn.execute(
        "SELECT w.canon_follow, w.canon_adopted_from_version, v.version "
        "FROM workflows w JOIN workflow_versions v ON v.id = w.current_version_id "
        "WHERE w.id = %s",
        (workflow_id,),
    ).fetchone()
    return dict(row)
