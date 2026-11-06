"""SQL membership projected from immutable workflow definitions."""

from __future__ import annotations
import json
from yoke_contracts.lifecycle_status import (
    successful_task_stage_ids,
    terminal_stage_ids,
)


def membership_sql(
    db, status: str, *, item_alias: str = "i", kind: str = "task_success"
) -> str:
    """Build a version-scoped predicate using the shared pure model."""
    rows = db.query_quiet("SELECT id, definition_json FROM workflow_versions")
    classify = (
        successful_task_stage_ids if kind == "task_success" else terminal_stage_ids
    )
    clauses = []
    for version_id, raw in rows:
        definition = json.loads(raw) if isinstance(raw, str) else raw
        values = ", ".join(
            "'" + value.replace("'", "''") + "'"
            for value in sorted(classify(definition))
        )
        if values:
            clauses.append(
                f"({item_alias}.workflow_version_id = {int(version_id)} AND {status} IN ({values}))"
            )
    return "(" + " OR ".join(clauses) + ")" if clauses else "FALSE"
