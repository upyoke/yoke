"""Migrate registered project test commands into executable QA plans."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one, query_rows
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


def _command(raw: Any) -> str:
    try:
        payload = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return ""
    command = payload.get("command") if isinstance(payload, dict) else None
    return str(command).strip() if isinstance(command, str) else ""


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
                f"Project-owned {scope} verification migrated into the "
                "shared Command method."
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


def _plan_for_merge_verification(
    conn: Any,
    *,
    project_id: int,
    project: str,
    command: str,
    timeout_seconds: int,
) -> int:
    marker = _p(conn)
    slug = "pre-merge-verification"
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
            name="Pre-merge verification",
            description=(
                "Project-owned verification executed after rebase and before "
                "the merge is finalized."
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
            "case_key": "post-rebase",
            "position": 1,
            "method_id": "command",
            "instructions": (
                "Run project verification after rebasing onto the merge target."
            ),
            "expected_outcome": "The command exits successfully.",
            "method_config": {
                "command": command,
                "timeout_seconds": timeout_seconds,
                "execution_point": "post_rebase_merge",
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


def migrate_registered_commands(
    conn: Any, *, retire_legacy: bool = True,
) -> dict:
    """Create one Command-method plan per registered command and attach it.

    Scope-to-transition mapping is explicit: quick runs when implementation
    enters review, full after implementation review (or at ``done`` for short
    workflows), e2e at release (or ``done``), and smoke at done/post-deploy.
    Workflows without either mapped transition simply do not get that default.
    """
    rows = query_rows(
        conn,
        "SELECT s.project_id, p.slug AS project, s.entry_key AS scope, "
        "s.payload FROM project_structure s "
        "JOIN projects p ON p.id=s.project_id "
        "WHERE s.family='command_definitions' "
        "AND s.attachment_value='project' "
        "ORDER BY p.slug, s.entry_key",
    )
    merge_rows = query_rows(
        conn,
        "SELECT s.project_id, p.slug AS project, s.payload "
        "FROM project_structure s "
        "JOIN projects p ON p.id=s.project_id "
        "WHERE s.family='merge_verification' "
        "AND s.attachment_value='project' "
        "ORDER BY p.slug",
    )
    workflows = _workflow_stages(conn)
    migrated: list[dict] = []
    skipped: list[dict] = []
    for row in rows:
        scope = str(row_value(row, "scope", 2))
        command = _command(row_value(row, "payload", 3))
        if scope not in COMMAND_SCOPE_POLICIES or not command:
            skipped.append({
                "project": str(row_value(row, "project", 1)),
                "scope": scope,
                "reason": "unsupported_scope_or_empty_command",
            })
            continue
        migrated.append(ensure_registered_command_plan(
            conn,
            project_id=int(row_value(row, "project_id", 0)),
            project=str(row_value(row, "project", 1)),
            scope=scope,
            command=command,
        ))
    migrated_merge_verification: list[dict] = []
    for row in merge_rows:
        try:
            payload = json.loads(
                str(row_value(row, "payload", 2) or "{}")
            )
        except (TypeError, ValueError):
            payload = {}
        command = (
            str(payload.get("command") or "").strip()
            if isinstance(payload, dict) else ""
        )
        timeout_seconds = (
            payload.get("timeout_seconds")
            if isinstance(payload, dict) else None
        )
        if (
            not command
            or not isinstance(timeout_seconds, int)
            or timeout_seconds < 1
        ):
            skipped.append({
                "project": str(row_value(row, "project", 1)),
                "scope": "merge_verification",
                "reason": "invalid_command_or_timeout",
            })
            continue
        plan_id = _plan_for_merge_verification(
            conn,
            project_id=int(row_value(row, "project_id", 0)),
            project=str(row_value(row, "project", 1)),
            command=command,
            timeout_seconds=timeout_seconds,
        )
        attached_workflows = []
        for workflow_id in ("issue", "epic"):
            if "release" not in workflows.get(workflow_id, set()):
                continue
            set_project_default(
                conn,
                plan_id=plan_id,
                workflow_id=workflow_id,
                transition_id="release",
                qa_phase="verification",
            )
            attached_workflows.append(workflow_id)
        migrated_merge_verification.append({
            "project": str(row_value(row, "project", 1)),
            "plan_id": plan_id,
            "transition_id": "release",
            "workflow_ids": attached_workflows,
        })
    retired_rows = 0
    if retire_legacy and skipped:
        raise RuntimeError(
            "legacy QA settings could not be migrated: "
            + json.dumps(skipped, sort_keys=True)
        )
    if retire_legacy and (rows or merge_rows):
        marker = _p(conn)
        project_ids = sorted({
            int(row_value(row, "project_id", 0))
            for row in [*rows, *merge_rows]
        })
        for project_id in project_ids:
            cursor = conn.execute(
                "DELETE FROM project_structure "
                f"WHERE project_id={marker} "
                "AND family IN ('command_definitions', 'merge_verification')",
                (project_id,),
            )
            retired_rows += max(0, int(cursor.rowcount or 0))
        conn.commit()
    return {
        "migrated": migrated,
        "migrated_merge_verification": migrated_merge_verification,
        "skipped": skipped,
        "retired_legacy_rows": retired_rows,
    }


__all__ = [
    "COMMAND_SCOPE_POLICIES",
    "ensure_registered_command_plan",
    "migrate_registered_commands",
]
