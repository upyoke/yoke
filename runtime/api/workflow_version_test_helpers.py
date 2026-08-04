"""Focused workflow-version fixtures shared by registry-authority tests."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.builtin_workflow_canon import canon_generations
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.workflow_definition_codec import canonical_definition_json
from yoke_core.domain.workflow_registry import publish_workflow_version


def current_workflow_version(conn: Any, workflow_id: str = "issue") -> int:
    """The version number *this* database converged the workflow to.

    Tests ask rather than assume. A version number is a position in one
    universe's own sequence, so what a freshly converged database lands on is
    a fact about that database; a constant naming it would be the same fiction
    that let a staging environment publishing on its own schedule look like
    corruption.
    """
    row = conn.execute(
        "SELECT v.version FROM workflows w "
        "JOIN workflow_versions v ON v.id = w.current_version_id "
        "WHERE w.id = %s",
        (workflow_id,),
    ).fetchone()
    if row is None:
        raise AssertionError(f"workflow {workflow_id!r} has no current version")
    return int(tuple(row.values())[0] if hasattr(row, "values") else row[0])


def publish_issue_completion_stage(
    conn: Any,
    *,
    stage_id: str = "archived",
    generated_children: Optional[str] = None,
) -> dict:
    """Publish an Issue version whose successful terminal follows ``done``."""
    definition = builtin_workflow_definition("issue")["definition"]
    previous_stage_ids = [stage["id"] for stage in definition["stages"]]
    definition["stages"].append(
        {
            "id": stage_id,
            "label": stage_id,
            "gates": [],
        }
    )
    definition["terminal_stage_ids"] = [stage_id]
    definition["transitions"].append(
        {
            "from_stage_id": "done",
            "to_stage_id": stage_id,
        }
    )
    definition["skill_bindings"][-1]["through_stage_id"] = stage_id
    definition["stage_mapping"] = {
        previous_stage_id: previous_stage_id for previous_stage_id in previous_stage_ids
    }
    if generated_children is not None:
        definition["policies"]["generated_children"] = generated_children
    return publish_workflow_version(
        conn,
        workflow_id="issue",
        definition=definition,
    )


def seed_generation_lacking_file_budget(conn) -> tuple[int, int]:
    """Give this universe a Dash version predating the File Budget axis.

    Seeded as data rather than published through the registry: the definition
    is real history, and history is older than the schema the current
    validator describes.
    """
    generation = next(
        candidate for candidate in canon_generations("dash")
        if "file_budget" not in candidate.definition["policies"]
    )
    version = int(
        conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM workflow_versions "
            "WHERE workflow_id = 'dash'"
        ).fetchone()[0]
    )
    version_id = conn.execute(
        "INSERT INTO workflow_versions "
        "(workflow_id, version, definition_schema_version, definition_json, "
        "definition_digest, published_at, immutable_at) "
        "VALUES ('dash', %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            version,
            int(generation.definition["schema_version"]),
            canonical_definition_json(generation.definition),
            generation.digest,
            generation.published_at,
            generation.published_at,
        ),
    ).fetchone()[0]
    conn.commit()
    return int(version_id), version


__all__ = [
    "current_workflow_version",
    "publish_issue_completion_stage",
    "seed_generation_lacking_file_budget",
]
