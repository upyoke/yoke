"""Shared reads and stage checks for item workflow migration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.workflow_runtime import WorkflowRuntime


def marker(conn: Any) -> str:
    """Return the connected database's parameter marker."""
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def dict_rows(cursor: Any) -> list[dict[str, Any]]:
    """Normalize a result cursor across Postgres and SQLite row factories."""
    rows = cursor.fetchall()
    if not rows:
        return []
    if hasattr(rows[0], "keys"):
        return [dict(row) for row in rows]
    columns = [str(value[0]) for value in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def mapped_stage(
    source: WorkflowRuntime,
    target: WorkflowRuntime,
    stage_id: str,
) -> str | None:
    """Resolve one source stage through the target's adjacent-version map."""
    if stage_id not in source.stage_ids:
        return None
    if stage_id in target.stage_ids:
        return stage_id
    mapping = target.definition.get("stage_mapping")
    if (
        target.version == source.version + 1
        and isinstance(mapping, Mapping)
        and stage_id in mapping
    ):
        return str(mapping[stage_id])
    return None


def stored_stage_conflict(
    source: WorkflowRuntime,
    target: WorkflowRuntime,
    *,
    binding: str,
    stage_id: str,
) -> str | None:
    """Explain why a durable stage reference cannot survive the migration."""
    mapped = mapped_stage(source, target, stage_id)
    if mapped is None:
        return f"{binding} targets undeclared stage {stage_id!r}"
    if mapped != stage_id:
        return (
            f"{binding} targets stage {stage_id!r}, which maps to {mapped!r}; "
            "the stored binding cannot be rewritten safely"
        )
    return None


def source_stage_for_target(
    source: WorkflowRuntime,
    target: WorkflowRuntime,
    target_stage_id: str,
) -> str | None:
    """Resolve one target stage back to its source identity."""
    mapping = target.definition.get("stage_mapping")
    if target.version == source.version + 1 and isinstance(mapping, Mapping):
        matches = [
            str(source_stage_id)
            for source_stage_id, mapped_stage_id in mapping.items()
            if str(mapped_stage_id) == target_stage_id
        ]
        return matches[0] if len(matches) == 1 else None
    return target_stage_id if target_stage_id in source.stage_ids else None


def gate_signature(
    runtime: WorkflowRuntime,
    stage_id: str,
    gate_id: str,
) -> tuple[tuple[str, str | None], ...]:
    """Return the exact mode-bearing references for one gate at one stage."""
    return tuple(
        (str(gate["id"]), gate.get("mode"))
        for gate in runtime.gates_for_stage(stage_id)
        if str(gate["id"]) == gate_id
    )


__all__ = [
    "dict_rows",
    "gate_signature",
    "mapped_stage",
    "marker",
    "source_stage_for_target",
    "stored_stage_conflict",
]
