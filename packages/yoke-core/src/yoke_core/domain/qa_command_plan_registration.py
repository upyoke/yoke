"""Register project verification commands as executable QA plans."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.project_checkout_locations import checkout_for_project_id
from yoke_core.domain.project_identity import row_value
from yoke_core.domain.project_verification_posture import (
    REGISTERED_COMMAND_PLAN_PREFIX,
    require_no_attestation,
)
from yoke_core.domain.qa_command_argv_presence import require_argv_present
from yoke_core.domain.qa_command_invocation import (
    canonicalize_registered_command,
)
from yoke_core.domain.qa_command_scope_routing import (
    capability_settings,
    default_workflow,
    workflow_for_scope,
)
from yoke_core.domain.qa_plan_attachments import set_project_default
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.workflow_registry import list_current_workflows


#: ``ci_routable`` is the DEFAULT for each scope, not a verdict. The
#: repository's own test suite is what a CI workflow already runs on every
#: pull request, so those scopes default to CI. The deployed-environment
#: scopes default to the local runner because a site behind a base URL is
#: often unreachable from CI — but whether it actually is belongs to the
#: project, which overrides this by naming the workflow that runs the scope
#: (see :mod:`yoke_core.domain.qa_command_scope_routing`).
COMMAND_SCOPE_POLICIES = {
    "quick": {
        "preferred_transition": "reviewing-implementation",
        "fallback_transition": "done",
        "qa_phase": "verification",
        "ci_routable": True,
    },
    "full": {
        "preferred_transition": None,
        "fallback_transition": None,
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

#: Local runner: runs the command in the item's worktree.
LOCAL_COMMAND_METHOD_ID = "command"
#: CI runner: dispatches the project's declared workflow for the lane.
CI_COMMAND_METHOD_ID = "command-ci"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def declared_ci_workflow(conn: Any, project_id: int) -> str:
    """Return the project's default CI workflow filename, or empty.

    A project that names its required-status-check workflow is telling Yoke
    where its suite already runs. This is the project-wide default; a scope
    the project maps explicitly runs the workflow that mapping names instead
    (see :mod:`yoke_core.domain.qa_command_scope_routing`). A project with no
    declaration keeps the local runner.
    """
    return default_workflow(capability_settings(conn, int(project_id)))


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
    slug = f"{REGISTERED_COMMAND_PLAN_PREFIX}{scope}"
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
        # Retained whichever runner runs: it is what the local
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


def policy_transitions(conn: Any, policy: dict[str, Any]) -> dict[str, str]:
    """Map each workflow to the stage this scope's plan attaches at."""
    preferred = policy["preferred_transition"]
    if preferred is None:
        return {}
    fallback = policy["fallback_transition"]
    return {
        workflow_id: str(preferred if preferred in stage_ids else fallback)
        for workflow_id, stage_ids in _workflow_stages(conn).items()
        if (preferred if preferred in stage_ids else fallback) in stage_ids
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
    require_no_attestation(
        conn,
        project_id=int(project_id),
        project=project,
        ci_method_id=CI_COMMAND_METHOD_ID,
    )
    command = canonicalize_registered_command(str(command).strip())
    if not command:
        raise ValueError("registered command must be non-empty")
    presence = require_argv_present(
        command,
        checkout=checkout_for_project_id(int(project_id)),
        project=project,
        scope=scope,
    )
    policy = COMMAND_SCOPE_POLICIES[scope]
    ci_workflow = workflow_for_scope(
        conn,
        project_id=int(project_id),
        scope=scope,
        default_routable=bool(policy["ci_routable"]),
    )
    plan_id = _plan_for_scope(
        conn,
        project_id=int(project_id),
        project=project,
        scope=scope,
        command=command,
        ci_workflow=ci_workflow,
    )
    qa_phase = str(policy["qa_phase"])
    transitions = policy_transitions(conn, policy)
    marker = _p(conn)
    conn.execute(
        f"DELETE FROM qa_plan_project_defaults WHERE plan_id={marker}",
        (plan_id,),
    )
    conn.commit()
    for workflow_id, transition_id in transitions.items():
        set_project_default(
            conn,
            plan_id=plan_id,
            workflow_id=workflow_id,
            transition_id=transition_id,
            qa_phase=qa_phase,
        )
    return {
        "project": project,
        "scope": scope,
        "plan_id": plan_id,
        "transitions": transitions,
        "qa_phase": qa_phase,
        "workflow_ids": list(transitions),
        "ci_workflow": ci_workflow,
        "argv_verification": presence.reason_code,
        "argv_verification_detail": presence.message,
    }


__all__ = [
    "CI_COMMAND_METHOD_ID",
    "COMMAND_SCOPE_POLICIES",
    "LOCAL_COMMAND_METHOD_ID",
    "declared_ci_workflow",
    "ensure_registered_command_plan",
    "policy_transitions",
]
