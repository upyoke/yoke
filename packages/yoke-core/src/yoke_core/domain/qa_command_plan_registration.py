"""Register project verification commands as executable QA plans."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one, query_rows, query_scalar
from yoke_core.domain.project_identity import row_value
from yoke_core.domain.projects_seed_ci_workflow import CI_WORKFLOW_CAPABILITY_TYPE
from yoke_core.domain.qa_plan_attachments import set_project_default
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.workflow_registry import list_current_workflows


#: ``ci_routable`` marks the scopes whose verification is the repository's
#: own test suite — exactly what a CI workflow already runs on every pull
#: request. The deployed-environment scopes are not routable: they assert
#: against a running site behind a base URL that CI has no access to.
COMMAND_SCOPE_POLICIES = {
    "quick": {
        "preferred_transition": "reviewing-implementation",
        "fallback_transition": "done",
        "qa_phase": "verification",
        "ci_routable": True,
    },
    "full": {
        "preferred_transition": "reviewed-implementation",
        "fallback_transition": "done",
        "qa_phase": "verification",
        "ci_routable": True,
    },
    "e2e": {
        "preferred_transition": "release",
        "fallback_transition": "done",
        "qa_phase": "verification",
        "ci_routable": False,
    },
    "smoke": {
        "preferred_transition": "done",
        "fallback_transition": "done",
        "qa_phase": "post_deploy",
        "ci_routable": False,
    },
}

#: Local executor: runs the command in the item's worktree.
LOCAL_COMMAND_METHOD_ID = "command"
#: CI executor: dispatches the project's declared workflow for the lane.
CI_COMMAND_METHOD_ID = "command-ci"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def declared_ci_workflow(conn: Any, project_id: int) -> str:
    """Return the project's declared CI workflow filename, or empty.

    A project that names its required-status-check workflow is telling
    Yoke where its suite already runs; registration routes the repository
    verification scopes there instead of onto the developer machine. A
    project with no declaration keeps the local executor.
    """
    marker = _p(conn)
    raw = query_scalar(
        conn,
        "SELECT COALESCE(settings, '{}') FROM project_capabilities "
        f"WHERE project_id={marker} AND type={marker}",
        (int(project_id), CI_WORKFLOW_CAPABILITY_TYPE),
    )
    if not raw:
        return ""
    try:
        settings = json.loads(str(raw))
    except (TypeError, ValueError):
        return ""
    if not isinstance(settings, dict):
        return ""
    return str(settings.get("workflow_file") or "").strip()


def _plan_for_scope(
    conn: Any,
    *,
    project_id: int,
    project: str,
    scope: str,
    command: str,
    ci_workflow: str = "",
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
    method_config: dict[str, Any] = {
        # Retained whichever executor runs: it is what the local
        # `command` fallback executes, and it documents the verification
        # the CI workflow is expected to be running.
        "command": command,
        "registered_scope": scope,
        "requires_base_url": scope in {"e2e", "smoke"},
    }
    if ci_workflow:
        method_config["ci_workflow"] = ci_workflow
    replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[{
            "case_key": scope,
            "position": 1,
            "method_id": (
                CI_COMMAND_METHOD_ID if ci_workflow else LOCAL_COMMAND_METHOD_ID
            ),
            "instructions": (
                f"Run the project's {scope} verification"
                + (" on its CI workflow." if ci_workflow else " command.")
            ),
            "expected_outcome": (
                "The CI run concludes successfully."
                if ci_workflow
                else "The command exits successfully."
            ),
            "method_config": method_config,
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
    policy = COMMAND_SCOPE_POLICIES[scope]
    ci_workflow = (
        declared_ci_workflow(conn, int(project_id))
        if policy["ci_routable"]
        else ""
    )
    plan_id = _plan_for_scope(
        conn,
        project_id=int(project_id),
        project=project,
        scope=scope,
        command=command,
        ci_workflow=ci_workflow,
    )
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
        "ci_workflow": ci_workflow,
    }


def _registered_scope_bindings(conn: Any) -> list[dict]:
    """Return every project's registered scopes with their current binding."""
    return list(query_rows(
        conn,
        "SELECT p.project_id AS project_id, pr.slug AS project, "
        "p.slug AS plan_slug, c.method_id AS method_id, "
        "c.method_config AS method_config "
        "FROM qa_plans p "
        "JOIN projects pr ON pr.id=p.project_id "
        "JOIN qa_plan_cases c ON c.plan_id=p.id "
        "WHERE p.retired_at IS NULL "
        "AND substr(p.slug, 1, 19)='registered-command-' "
        "ORDER BY p.project_id, p.slug",
    ))


def converge_registered_command_plans(conn: Any) -> list[dict]:
    """Rebind registered verification scopes onto the executor code selects.

    Where a project's verification command *runs* is executable
    configuration, not birth-only data: it follows from code plus the
    project's declared ``ci_workflow_file`` capability. Registration alone
    cannot keep that current, because it happens once — a project that
    declares its CI workflow after first registering its command, or a
    deploy that adds CI routing to scopes already registered, would leave
    the old binding in place forever.

    Only bindings that actually disagree with what code would choose today
    are rewritten, so a converged boot writes nothing, and a project that
    drops its declaration rebinds back to the local executor.
    """
    converged: list[dict] = []
    for row in _registered_scope_bindings(conn):
        scope = str(row["plan_slug"]).removeprefix("registered-command-")
        policy = COMMAND_SCOPE_POLICIES.get(scope)
        if policy is None:
            continue
        try:
            config = json.loads(str(row["method_config"] or "{}"))
        except (TypeError, ValueError):
            continue
        command = str(config.get("command") or "").strip() if isinstance(
            config, dict
        ) else ""
        if not command:
            continue
        project_id = int(row["project_id"])
        ci_workflow = (
            declared_ci_workflow(conn, project_id)
            if policy["ci_routable"]
            else ""
        )
        desired_method = (
            CI_COMMAND_METHOD_ID if ci_workflow else LOCAL_COMMAND_METHOD_ID
        )
        current_workflow = str(config.get("ci_workflow") or "").strip()
        if (
            str(row["method_id"]) == desired_method
            and current_workflow == ci_workflow
        ):
            continue
        ensure_registered_command_plan(
            conn,
            project_id=project_id,
            project=str(row["project"]),
            scope=scope,
            command=command,
        )
        converged.append({
            "project": str(row["project"]),
            "scope": scope,
            "method_id": desired_method,
            "ci_workflow": ci_workflow,
        })
    return converged


__all__ = [
    "CI_COMMAND_METHOD_ID",
    "COMMAND_SCOPE_POLICIES",
    "LOCAL_COMMAND_METHOD_ID",
    "converge_registered_command_plans",
    "declared_ci_workflow",
    "ensure_registered_command_plan",
]
