"""Read-only workflow definition: family, per-type progressions, gate
points, and deployment flows.

The read behind ``workflows.definition.get``. The lifecycle half serves
the engine's hardcoded definition as data — the workflow family
(:data:`~yoke_core.domain.lifecycle_enums.LIFECYCLE_FAMILY`), the ordered
status progression per item type, and the gate families the authoritative
status gate evaluates at each status
(:data:`~yoke_core.domain.backlog_status_gate_points.STATUS_GATE_POINTS`).
Stages are served raw and complete; condensing is presentation, not data.
The lifecycle definition is universe-wide today: no project changes it.

The flows half reads ``deployment_flows`` rows — optionally filtered to
one project (slug or id) — with each flow's stage names parsed out of its
stages JSON so consumers need not re-parse the stored column.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import db_helpers
from yoke_core.domain.backlog_status_gate_points import STATUS_GATE_POINTS
from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.lifecycle_enums import LIFECYCLE_FAMILY
from yoke_core.domain.lifecycle_progression import (
    EPIC_PROGRESSION,
    ISSUE_PROGRESSION,
)
from yoke_core.domain.project_identity import resolve_project_id

#: (item type, its ordered status progression), matching the closed
#: ``items.type`` vocabulary.
WORKFLOW_TYPE_PROGRESSIONS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("issue", ISSUE_PROGRESSION),
    ("epic", EPIC_PROGRESSION),
)

#: Row keys every served flow carries.
FLOW_FIELDS = (
    "id",
    "name",
    "target_env",
    "on_failure",
    "stage_names",
    "project",
)


def _gates_for_progression(
    progression: Tuple[str, ...],
) -> List[Dict[str, str]]:
    """Gate rows for one type: only statuses that type can reach."""
    return [
        {"at_status": status, "gate": family}
        for status in progression
        for family in STATUS_GATE_POINTS.get(status, ())
    ]


def _stage_names(raw_stages: Any) -> List[str]:
    """Each stage's own identifying field, parsed from the stages JSON.

    Executor-shaped stages identify by ``name``, kind-shaped stages by
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

    ``project`` (slug or id, resolved server-side) filters the flows
    list; the lifecycle half is identical whatever the filter, because
    the definition is universe-wide today.
    """
    conn = db_helpers.connect()
    try:
        clause = ""
        params: Tuple[Any, ...] = ()
        if project:
            clause = "WHERE df.project_id = %s "
            params = (resolve_project_id(conn, project),)
        rows = conn.execute(
            "SELECT df.id, df.name, df.target_env, df.on_failure, "
            "df.stages, p.slug AS project "
            "FROM deployment_flows df "
            "JOIN projects p ON p.id = df.project_id "
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
                "target_env": row.get("target_env"),
                "on_failure": row.get("on_failure"),
                "stage_names": _stage_names(row.get("stages")),
                "project": row.get("project"),
            })
    finally:
        conn.close()

    return {
        "family": LIFECYCLE_FAMILY,
        "types": [
            {
                "type": type_name,
                "stages": list(progression),
                "gates": _gates_for_progression(progression),
            }
            for type_name, progression in WORKFLOW_TYPE_PROGRESSIONS
        ],
        "flows": flows,
    }


__all__ = [
    "FLOW_FIELDS",
    "WORKFLOW_TYPE_PROGRESSIONS",
    "get_workflows_definition",
]
