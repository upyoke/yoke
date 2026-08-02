"""Register project verification commands as executable QA plans."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.project_identity import row_value
from yoke_core.domain.qa_plan_attachments import set_project_default
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.workflow_registry import list_current_workflows


COMMAND_SCOPE_POLICIES = {
    "quick": {
        "preferred_transition": "reviewing-implementation",
        "fallback_transition": "done",
        "qa_phase": "verification",
    },
    "full": {
        "preferred_transition": "reviewed-implementation",
        "fallback_transition": "done",
        "qa_phase": "verification",
    },
    "e2e": {
        "preferred_transition": "release",
        "fallback_transition": "done",
        "qa_phase": "verification",
    },
    "smoke": {
        "preferred_transition": "done",
        "fallback_transition": "done",
        "qa_phase": "post_deploy",
    },
}


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _plan_for_scope(
    conn: Any, *, project_id: int, project: str, scope: str, command: str,
) -> int:
    marker = _p(conn)
    slug = f"registered-command-{scope}"
    existing = query_one(
        conn,
        f"SELECT id FROM qa_plans WHERE project_id={marker} AND slug={marker}",
        (project_id, slug),
    )
    if existing is None:
        plan_id = int(create_plan(
            conn,
            project=project,
            slug=slug,
            name=f"{scope.title()} command",
            description=(
                f"Project-owned {scope} verification registered through "
                "the shared Command method."
            ),
        )["id"])
    else:
        plan_id = int(row_value(existing, "id", 0))
        conn.execute(
            f"UPDATE qa_plans SET retired_at=NULL WHERE id={marker}",
            (plan_id,),
        )
        conn.commit()
    replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[{
            "case_key": scope,
            "position": 1,
            "method_id": "command",
            "instructions": f"Run the project's {scope} verification command.",
            "expected_outcome": "The command exits successfully.",
            "method_config": {
                "command": command,
                "registered_scope": scope,
                "requires_base_url": scope in {"e2e", "smoke"},
            },
        }],
    )
    return plan_id


def _workflow_stages(conn: Any) -> dict[str, set[str]]:
    return {
        str(row["id"]): {
            str(stage["id"])
            for stage in row["definition"].get("stages", [])
        }
        for row in list_current_workflows(conn)
    }


def ensure_registered_command_plan(
    conn: Any,
    *,
    project_id: int,
    project: str,
    scope: str,
    command: str,
) -> dict:
    """Converge one registered scope onto its plan and workflow defaults."""
    if scope not in COMMAND_SCOPE_POLICIES:
        raise ValueError(f"unsupported registered command scope {scope!r}")
    command = str(command).strip()
    if not command:
        raise ValueError("registered command must be non-empty")
    plan_id = _plan_for_scope(
        conn,
        project_id=int(project_id),
        project=project,
        scope=scope,
        command=command,
    )
    policy = COMMAND_SCOPE_POLICIES[scope]
    preferred = str(policy["preferred_transition"])
    fallback = str(policy["fallback_transition"])
    qa_phase = str(policy["qa_phase"])
    workflows = _workflow_stages(conn)
    attached_workflows = []
    transitions = {}
    for workflow_id, stage_ids in workflows.items():
        transition_id = preferred if preferred in stage_ids else fallback
        if transition_id not in stage_ids:
            continue
        set_project_default(
            conn,
            plan_id=plan_id,
            workflow_id=workflow_id,
            transition_id=transition_id,
            qa_phase=qa_phase,
        )
        attached_workflows.append(workflow_id)
        transitions[workflow_id] = transition_id
    return {
        "project": project,
        "scope": scope,
        "plan_id": plan_id,
        "transitions": transitions,
        "qa_phase": qa_phase,
        "workflow_ids": attached_workflows,
    }


__all__ = [
    "COMMAND_SCOPE_POLICIES",
    "ensure_registered_command_plan",
]
