"""Stage vocabulary projected from immutable workflow versions."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.workflow_registry import (
    WorkflowRegistryError,
    definition_digest,
)


def published_workflow_stage_ids(conn: Any) -> tuple[str, ...]:
    """Return every stage id accepted by an immutable published version."""
    rows = conn.execute(
        "SELECT workflow_id, version, definition_json, definition_digest "
        "FROM workflow_versions ORDER BY workflow_id, version"
    ).fetchall()
    stage_ids: set[str] = set()
    for raw in rows:
        row = dict(raw)
        try:
            definition = json.loads(str(row["definition_json"]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise WorkflowRegistryError(
                "stored workflow definition is not valid JSON"
            ) from exc
        if (
            not isinstance(definition, dict)
            or definition_digest(definition) != row["definition_digest"]
        ):
            raise WorkflowRegistryError(
                f"workflow version {row['workflow_id']}@{row['version']} "
                "does not match its immutable digest"
            )
        stage_ids.update(
            str(stage["id"]) for stage in definition["stages"]
        )
    return tuple(sorted(stage_ids))


__all__ = ["published_workflow_stage_ids"]
