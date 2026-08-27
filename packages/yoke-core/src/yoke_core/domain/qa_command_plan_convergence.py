"""Keep every registered verification scope bound to the runner code picks.

Where a project's verification command *runs* is executable configuration, not
birth-only data: it follows from code plus the project's declared
``ci_workflow_file`` capability. Registration alone cannot keep that current,
because registration happens once — a project that declares its CI workflow
after first registering its command, or a deploy that adds CI routing to scopes
already registered, would otherwise keep the old binding forever.

This runs on boot, which is why it lives beside the registration it converges
rather than inside it: registration answers "bind this command", and this
answers "is every already-bound command still bound where code would put it".
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_command_invocation import (
    canonicalize_registered_command,
    rewrite_retired_watch_pytest_commands,
)
from yoke_core.domain.project_verification_posture import (
    REGISTERED_COMMAND_PLAN_PREFIX,
)
from yoke_core.domain.qa_command_plan_registration import (
    CI_COMMAND_METHOD_ID,
    COMMAND_SCOPE_POLICIES,
    LOCAL_COMMAND_METHOD_ID,
    ensure_registered_command_plan,
    policy_transitions,
)
from yoke_core.domain.qa_command_scope_routing import (
    capability_settings,
    scope_workflow,
)
from yoke_core.domain.qa_project_execution_target import (
    ENVIRONMENT_TARGET_MODE,
    PROJECT_COMMAND_SCOPES,
    RUNTIME_BASE_URL_TARGET_MODE,
    registered_command_target_mode,
)
from yoke_core.domain import db_backend


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _registered_scope_bindings(conn: Any) -> list[dict]:
    """Return every project's registered scopes with their current binding."""
    return list(query_rows(
        conn,
        "SELECT p.id AS plan_id, p.project_id AS project_id, pr.slug AS project, "
        "p.slug AS plan_slug, p.target_environment_id, c.method_id AS method_id, "
        "c.method_config AS method_config "
        "FROM qa_plans p "
        "JOIN projects pr ON pr.id=p.project_id "
        "JOIN qa_plan_cases c ON c.plan_id=p.id "
        "WHERE p.retired_at IS NULL "
        f"AND substr(p.slug, 1, {len(REGISTERED_COMMAND_PLAN_PREFIX)})="
        f"'{REGISTERED_COMMAND_PLAN_PREFIX}' "
        "ORDER BY p.project_id, p.slug",
    ))


def converge_registered_command_plans(conn: Any) -> list[dict]:
    """Rebind registered verification scopes onto the runner code selects.

    Where a project's verification command *runs* is executable
    configuration, not birth-only data: it follows from code plus the
    project's declared ``ci_workflow_file`` capability. Registration alone
    cannot keep that current, because it happens once — a project that
    declares its CI workflow after first registering its command, or a
    deploy that adds CI routing to scopes already registered, would leave
    the old binding in place forever.

    Only bindings that actually disagree with what code would choose today
    are rewritten, so a converged boot writes nothing, and a project that
    drops its declaration rebinds back to the local runner.
    """
    converged: list[dict] = []
    # One capability read per project rather than per binding: the bindings
    # arrive grouped by project and every scope of a project answers from the
    # same settings document.
    settings_by_project: dict[int, dict[str, Any]] = {}
    for row in _registered_scope_bindings(conn):
        scope = str(row["plan_slug"]).removeprefix(
            REGISTERED_COMMAND_PLAN_PREFIX
        )
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
        canonical = canonicalize_registered_command(command)
        project_id = int(row["project_id"])
        if project_id not in settings_by_project:
            settings_by_project[project_id] = capability_settings(conn, project_id)
        ci_workflow = scope_workflow(
            settings_by_project[project_id],
            scope=scope,
            default_routable=bool(policy["ci_routable"]),
        )
        desired_method = (
            CI_COMMAND_METHOD_ID if ci_workflow else LOCAL_COMMAND_METHOD_ID
        )
        current_workflow = str(config.get("ci_workflow") or "").strip()
        current_target_id = (
            int(row["target_environment_id"])
            if row["target_environment_id"] is not None
            else None
        )
        current_requires_base_url = bool(config.get("requires_base_url"))
        target_environment = (
            None
            if scope in PROJECT_COMMAND_SCOPES or current_target_id is None
            else str(current_target_id)
        )
        requires_base_url = (
            None
            if scope in PROJECT_COMMAND_SCOPES or current_target_id is not None
            else True if current_requires_base_url else None
        )
        try:
            target_mode = registered_command_target_mode(
                scope=scope,
                ci_workflow=ci_workflow,
                target_environment=target_environment,
                requires_base_url=requires_base_url,
            )
        except ValueError as exc:
            converged.append({
                "project": str(row["project"]),
                "scope": scope,
                "method_id": str(row["method_id"]),
                "ci_workflow": current_workflow,
                "target_error": str(exc),
            })
            continue
        desired_target_id = (
            current_target_id if target_mode == ENVIRONMENT_TARGET_MODE else None
        )
        desired_requires_base_url = target_mode == RUNTIME_BASE_URL_TARGET_MODE
        current_transitions = {
            (str(default["workflow_id"]), str(default["transition_id"]))
            for default in query_rows(
                conn,
                "SELECT workflow_id, transition_id "
                "FROM qa_plan_project_defaults WHERE plan_id=" + _p(conn),
                (int(row["plan_id"]),),
            )
        }
        desired_transitions = set(policy_transitions(conn, policy).items())
        if (
            str(row["method_id"]) == desired_method
            and current_workflow == ci_workflow
            and current_transitions == desired_transitions
            and command == canonical
            and current_target_id == desired_target_id
            and current_requires_base_url == desired_requires_base_url
        ):
            continue
        ensure_registered_command_plan(
            conn,
            project_id=project_id,
            project=str(row["project"]),
            scope=scope,
            command=canonical,
            target_environment=target_environment,
            requires_base_url=requires_base_url,
        )
        converged.append({
            "project": str(row["project"]),
            "scope": scope,
            "method_id": desired_method,
            "ci_workflow": ci_workflow,
        })
    rewrite_retired_watch_pytest_commands(conn)
    return converged


__all__ = ["converge_registered_command_plans"]
