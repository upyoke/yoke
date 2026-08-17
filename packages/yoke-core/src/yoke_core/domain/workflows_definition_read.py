"""Read current immutable workflows, gate catalog, and deployment flows.

The read behind ``workflows.definition.get``. Workflow identities and their
selected version rows are universe-wide. Definitions own ordered stages,
labels, descriptions, transition edges, gate placement, entry surfaces,
registered skill bindings, and policy. The engine-owned gate catalog owns
the stable gate strings those definitions reference.

The flows half reads ``deployment_flows`` rows — optionally filtered to
one project (slug or id) — with each flow's stage names parsed out of its
stages JSON so consumers need not re-parse the stored column.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import db_helpers
from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.workflow_gate_catalog import workflow_gate_catalog
from yoke_core.domain.workflow_registry import list_current_workflows

#: Row keys every served flow carries.
FLOW_FIELDS = (
    "id",
    "name",
    "target_tier",
    "target_environment_id",
    "target_environment",
    "status",
    "on_failure",
    "stage_names",
    "project",
)


def _stage_names(raw_stages: Any) -> List[str]:
    """Each stage's own identifying field, parsed from the stages JSON.

    Skill-shaped stages identify by ``name``, kind-shaped stages by
    ``kind``. Unparseable or non-list JSON serves an empty list rather
    than failing the whole read over one malformed row.
    """
    try:
        stages = (
            loads_text(raw_stages) if isinstance(raw_stages, str)
            else raw_stages
        )
    except ValueError:
        return []
    if not isinstance(stages, list):
        return []
    names: List[str] = []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        label = stage.get("name") or stage.get("kind")
        if label:
            names.append(str(label))
    return names


def get_workflows_definition(
    *,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    """The workflow definition, with flows optionally scoped to a project.

    ``project`` (slug or id, resolved server-side) filters only the project-owned
    flows list. Workflows and their gate catalog remain universe-wide.
    """
    conn = db_helpers.connect()
    try:
        clause = ""
        params: Tuple[Any, ...] = ()
        if project:
            clause = "WHERE df.project_id = %s "
            params = (resolve_project_id(conn, project),)
        rows = conn.execute(
            "SELECT df.id, df.name, df.target_tier, "
            "df.target_environment_id, e.name AS target_environment, "
            "df.status, df.on_failure, "
            "df.stages, p.slug AS project "
            "FROM deployment_flows df "
            "JOIN projects p ON p.id = df.project_id "
            "LEFT JOIN environments e ON e.id = df.target_environment_id "
            f"{clause}"
            "ORDER BY df.id ASC",
            params,
        ).fetchall()
        flows = []
        for raw in rows:
            row = dict(raw)
            flows.append({
                "id": row.get("id"),
                "name": row.get("name"),
                "target_tier": row.get("target_tier"),
                "target_environment_id": row.get("target_environment_id"),
                "target_environment": row.get("target_environment"),
                "status": row.get("status"),
                "on_failure": row.get("on_failure"),
                "stage_names": _stage_names(row.get("stages")),
                "project": row.get("project"),
            })
        workflows = list_current_workflows(conn)
    finally:
        conn.close()

    return {
        "family": "work-items",
        "workflows": workflows,
        "gate_catalog": workflow_gate_catalog(),
        "flows": flows,
    }


__all__ = [
    "FLOW_FIELDS",
    "get_workflows_definition",
]
