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
    ci_binding_for_scope,
    default_workflow,
    workflow_for_scope,
)
from yoke_core.domain.qa_plan_attachments import set_project_default
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_project_execution_target import (
    CI_COMMAND_METHOD_ID,
    ENVIRONMENT_TARGET_MODE,
    LOCAL_COMMAND_METHOD_ID,
    RUNTIME_BASE_URL_TARGET_MODE,
    registered_command_target_mode,
)
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


def _resolve_environment(
    conn: Any,
    *,
    project_id: int,
    reference: str,
) -> tuple[int, str]:
    """Resolve and validate an authorized plan environment before any write."""
    from yoke_core.domain.qa_execution_environment_target import (
        validate_plan_target_environment,
    )
    from yoke_core.domain.qa_hosted_runtime_identity import (
        resolve_plan_environment_reference,
    )

    target = resolve_plan_environment_reference(
        conn,
        plan_project_id=int(project_id),
        environment=reference,
    )
    environment_id = int(target["environment_id"])
    validate_plan_target_environment(
        conn,
        project_id=int(project_id),
        environment_id=environment_id,
    )
    return environment_id, (
        f"{target['site_name']}/{target['environment_name']}"
    )


def _plan_for_scope(
    conn: Any,
    *,
    project_id: int,
    project: str,
    scope: str,
    command: str,
    ci_workflow: str = "",
    target_environment_id: int | None = None,
    requires_base_url: bool = False,
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
            target_environment=(
                str(target_environment_id)
                if target_environment_id is not None
                else None
            ),
            infer_target_environment=False,
        )["id"])
    else:
        plan_id = int(row_value(existing, "id", 0))
    conn.execute(
        "UPDATE qa_plans SET retired_at=NULL, "
        f"target_environment_id={marker} WHERE id={marker}",
        (target_environment_id, plan_id),
    )
    conn.commit()
    method_config: dict[str, Any] = {
        # Retained whichever runner runs: it is what the local
        # `command` fallback executes, and it documents the verification
        # the CI workflow is expected to be running.
        "command": command,
        "registered_scope": scope,
        "requires_base_url": bool(requires_base_url),
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
    target_environment: str | None = None,
    requires_base_url: bool | None = None,
    refuse_unreachable_ci: bool = True,
) -> dict:
    """Converge one registered scope onto its plan and workflow defaults.

    ``refuse_unreachable_ci=False`` is for the boot-time convergence, which
    has no operator to fix a declared workflow the gate cannot reach and must
    not refuse to boot over one; it binds the local runner and reports why.
    """
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
    workflow_check = None
    if ci_workflow:
        ci_workflow, workflow_check = ci_binding_for_scope(
            conn,
            project_id=int(project_id),
            project=project,
            scope=scope,
            ci_workflow=ci_workflow,
            refuse_unreachable=refuse_unreachable_ci,
        )
    target_mode = registered_command_target_mode(
        scope=scope,
        ci_workflow=ci_workflow,
        target_environment=target_environment,
        requires_base_url=requires_base_url,
    )
    target_environment_id: int | None = None
    normalized_environment: str | None = None
    if target_mode == ENVIRONMENT_TARGET_MODE:
        target_environment_id, normalized_environment = _resolve_environment(
            conn,
            project_id=int(project_id),
            reference=str(target_environment),
        )
    plan_id = _plan_for_scope(
        conn,
        project_id=int(project_id),
        project=project,
        scope=scope,
        command=command,
        ci_workflow=ci_workflow,
        target_environment_id=target_environment_id,
        requires_base_url=target_mode == RUNTIME_BASE_URL_TARGET_MODE,
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
        "method_id": (
            CI_COMMAND_METHOD_ID if ci_workflow else LOCAL_COMMAND_METHOD_ID
        ),
        "target_mode": target_mode,
        "target_environment": normalized_environment,
        "requires_base_url": target_mode == RUNTIME_BASE_URL_TARGET_MODE,
        "argv_verification": presence.reason_code,
        "argv_verification_detail": presence.message,
        "ci_workflow_verification": (
            workflow_check.reason_code if workflow_check else ""
        ),
        "ci_workflow_verification_detail": (
            workflow_check.message if workflow_check else ""
        ),
    }


__all__ = [
    "CI_COMMAND_METHOD_ID",
    "COMMAND_SCOPE_POLICIES",
    "LOCAL_COMMAND_METHOD_ID",
    "declared_ci_workflow",
    "ensure_registered_command_plan",
    "policy_transitions",
]
