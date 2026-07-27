"""Project-owned Testing and Delivery defaults shown by Workflows."""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now, query_one, query_rows
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.workflow_registry import list_current_workflows


class WorkflowProjectDefaultError(ValueError):
    """A project default cannot be saved without weakening its scope."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _json_object(value: Any) -> dict:
    try:
        decoded = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _current_workflows(conn: Any) -> list[dict]:
    return [dict(row) for row in list_current_workflows(conn)]


def _selected_workflows(
    conn: Any, workflow_id: str, apply_to_all: bool,
) -> list[dict]:
    workflows = _current_workflows(conn)
    if apply_to_all:
        return workflows
    selected = [row for row in workflows if row["id"] == workflow_id]
    if not selected:
        raise WorkflowProjectDefaultError(
            f"workflow {workflow_id!r} does not exist"
        )
    return selected


def _qa_transition_ids(workflow: dict) -> tuple[str, ...]:
    transitions = []
    for stage in workflow["definition"].get("stages", []):
        if any(
            gate.get("id") == "qa_verification"
            for gate in stage.get("gates", [])
        ):
            transitions.append(str(stage["id"]))
    return tuple(transitions)


def list_testing_defaults(conn: Any) -> list[dict]:
    """Return each declared project × workflow × transition plan binding."""
    rows = query_rows(
        conn,
        "SELECT d.project_id, p.slug AS project, d.workflow_id, "
        "d.transition_id, d.plan_id, q.slug AS plan, q.name AS plan_name "
        "FROM qa_plan_project_defaults d "
        "JOIN projects p ON p.id=d.project_id "
        "JOIN qa_plans q ON q.id=d.plan_id "
        "ORDER BY p.slug, d.workflow_id, d.transition_id",
    )
    return [dict(row) for row in rows]


def set_testing_default(
    conn: Any,
    *,
    project: str,
    workflow_id: str,
    plan_id: int,
    apply_to_all: bool = False,
    actor_id: Optional[int] = None,
) -> dict:
    """Set one plan across every QA checkpoint in the selected workflow(s)."""
    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise WorkflowProjectDefaultError(f"project {project!r} not found")
    p = _p(conn)
    plan = query_one(
        conn,
        f"SELECT id FROM qa_plans WHERE id={p} AND project_id={p} "
        "AND retired_at IS NULL",
        (int(plan_id), int(identity.id)),
    )
    if plan is None:
        raise WorkflowProjectDefaultError(
            "test plan does not belong to the selected project"
        )
    selected = _selected_workflows(conn, workflow_id, apply_to_all)
    targets = [
        (str(row["id"]), transition_id)
        for row in selected
        for transition_id in _qa_transition_ids(row)
    ]
    if not targets:
        raise WorkflowProjectDefaultError(
            "the selected workflow has no QA verification checkpoint"
        )
    stamp = iso8601_now()
    selected_ids = [str(row["id"]) for row in selected]
    for selected_id in selected_ids:
        conn.execute(
            "DELETE FROM qa_plan_project_defaults "
            f"WHERE project_id={p} AND workflow_id={p}",
            (int(identity.id), selected_id),
        )
    for selected_id, transition_id in targets:
        conn.execute(
            "INSERT INTO qa_plan_project_defaults("
            "project_id, workflow_id, transition_id, qa_phase, plan_id, "
            "attached_at, attached_by_actor_id"
            f") VALUES ({', '.join([p] * 7)})",
            (
                int(identity.id), selected_id, transition_id, "verification",
                int(plan_id), stamp, actor_id,
            ),
        )
    conn.commit()
    return {
        "project_id": int(identity.id),
        "project": identity.slug,
        "workflow_ids": selected_ids,
        "plan_id": int(plan_id),
        "transition_count": len(targets),
    }


def _delivery_payload(conn: Any, project_id: int) -> dict:
    p = _p(conn)
    row = query_one(
        conn,
        "SELECT payload FROM project_structure "
        f"WHERE project_id={p} AND family='deploy_defaults' "
        "AND attachment_value='project' AND entry_key=''",
        (int(project_id),),
    )
    return _json_object(row["payload"]) if row is not None else {}


def list_delivery_defaults(conn: Any) -> list[dict]:
    """Return effective per-workflow flow choices, including legacy fallback."""
    workflows = [str(row["id"]) for row in _current_workflows(conn)]
    rows = query_rows(
        conn,
        "SELECT p.id AS project_id, p.slug AS project, s.payload "
        "FROM projects p JOIN project_structure s ON s.project_id=p.id "
        "WHERE s.family='deploy_defaults' "
        "AND s.attachment_value='project' AND s.entry_key='' "
        "ORDER BY p.slug",
    )
    result = []
    for row in rows:
        payload = _json_object(row["payload"])
        fallback = payload.get("deployment_flow")
        workflow_defaults = payload.get("workflow_defaults")
        declared = (
            workflow_defaults if isinstance(workflow_defaults, dict) else {}
        )
        for workflow_id in workflows:
            flow_id = declared.get(workflow_id, fallback)
            if isinstance(flow_id, str) and flow_id:
                result.append({
                    "project_id": int(row["project_id"]),
                    "project": str(row["project"]),
                    "workflow_id": workflow_id,
                    "flow_id": flow_id,
                })
    return result


def get_delivery_default(
    conn: Any, *, project: str, workflow_id: str,
) -> Optional[str]:
    """Resolve the workflow-specific choice, then the legacy project fallback."""
    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise WorkflowProjectDefaultError(f"project {project!r} not found")
    payload = _delivery_payload(conn, int(identity.id))
    declared = payload.get("workflow_defaults")
    if isinstance(declared, dict):
        selected = declared.get(workflow_id)
        if isinstance(selected, str) and selected:
            return selected
    fallback = payload.get("deployment_flow")
    return fallback if isinstance(fallback, str) and fallback else None


def set_delivery_default(
    conn: Any,
    *,
    project: str,
    workflow_id: str,
    flow_id: str,
    apply_to_all: bool = False,
) -> dict:
    """Set a project flow choice without changing any workflow version."""
    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise WorkflowProjectDefaultError(f"project {project!r} not found")
    p = _p(conn)
    flow = query_one(
        conn,
        f"SELECT id FROM deployment_flows WHERE id={p} AND project_id={p} "
        "AND status='active'",
        (flow_id, int(identity.id)),
    )
    if flow is None:
        raise WorkflowProjectDefaultError(
            "deployment flow does not belong to the selected project"
        )
    selected = _selected_workflows(conn, workflow_id, apply_to_all)
    payload = _delivery_payload(conn, int(identity.id))
    defaults = payload.get("workflow_defaults")
    defaults = dict(defaults) if isinstance(defaults, dict) else {}
    selected_ids = [str(row["id"]) for row in selected]
    for selected_id in selected_ids:
        defaults[selected_id] = flow_id
    payload["deployment_flow"] = payload.get("deployment_flow") or flow_id
    payload["workflow_defaults"] = defaults
    from yoke_core.domain.project_structure_write import (
        apply_patch_on_connection,
    )

    apply_patch_on_connection(
        conn,
        identity.slug,
        ops=[{
            "op": "put",
            "family": "deploy_defaults",
            "attachment": "project",
            "payload": payload,
        }],
    )
    conn.commit()
    return {
        "project_id": int(identity.id),
        "project": identity.slug,
        "workflow_ids": selected_ids,
        "flow_id": flow_id,
    }


def list_approval_actors(conn: Any) -> list[dict]:
    """Return the named-human roster available to an org-admin editor."""
    rows = query_rows(
        conn,
        "SELECT a.id, l.label FROM actors a "
        "JOIN actor_labels l ON l.actor_id=a.id AND l.surface='display' "
        "WHERE a.kind='human' ORDER BY LOWER(l.label), a.id",
    )
    return [{"id": int(row["id"]), "label": str(row["label"])} for row in rows]


__all__ = [
    "WorkflowProjectDefaultError",
    "get_delivery_default",
    "list_approval_actors",
    "list_delivery_defaults",
    "list_testing_defaults",
    "set_delivery_default",
    "set_testing_default",
]
