"""Resolve live session dispatch from an item's pinned workflow."""

from __future__ import annotations

import logging
from typing import Any, Optional

from . import db_backend
from .frontier_classify import classify_next_action
from .item_ref_resolution import resolve_internal_item_id
from .scheduler_routing import _compute_next_step
from .workflow_registry import WorkflowRegistryError
from .workflow_runtime import WorkflowRuntime, load_item_workflow_runtime

_logger = logging.getLogger(__name__)


def read_item_project_and_workflow(
    conn: Any,
    item_id: str,
) -> tuple[Optional[str], Optional[WorkflowRuntime]]:
    """Read project identity and a verified immutable workflow pin."""
    bare = resolve_internal_item_id(conn, item_id)
    if bare is None:
        return None, None
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        row = conn.execute(
            "SELECT p.slug AS project FROM items i "
            "LEFT JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id = {placeholder}",
            (bare,),
        ).fetchone()
    except (
        db_backend.operational_error_types(conn)
        + db_backend.database_error_types(conn)
    ) as exc:
        _logger.debug("session item workflow read failed: %s", exc)
        return None, None
    if row is None:
        return None, None
    project = row["project"] if hasattr(row, "keys") else row[0]
    try:
        workflow = load_item_workflow_runtime(conn, bare)
    except WorkflowRegistryError as exc:
        _logger.debug("session item workflow pin failed: %s", exc)
        return project, None
    return project, workflow


def live_next_step(
    workflow: WorkflowRuntime,
    stage_id: str,
) -> Optional[str]:
    """Return the definition-selected scheduler step for a live stage."""
    try:
        adapter = classify_next_action(workflow, stage_id)
    except ValueError:
        return None
    return _compute_next_step(
        adapter,
        probe_path_claim_activation=(
            workflow.requires_item_path_claim_probe(stage_id)
        ),
    ).next_step.value


__all__ = ["live_next_step", "read_item_project_and_workflow"]
