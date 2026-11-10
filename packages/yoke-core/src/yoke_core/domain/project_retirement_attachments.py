"""What stays attached to a retired project, and how to remove each kind.

Retirement deletes nothing. This report lists every kind of record still
attached, stored credentials first (names only, never values), with the exact
existing command that removes or changes each one, filled in with the
project's own names. Where no command exists the entry says so plainly.
"""

from __future__ import annotations

import json
import shlex
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_github_auth_models import GITHUB_CAPABILITY_TYPE
from yoke_core.domain.pulumi_state_capability import (
    CAPABILITY_TYPE as PULUMI_STATE_CAPABILITY,
    STACK_STATE_KEY,
)

NO_SECRET_COMMAND = (
    "No yoke command removes a stored capability secret; "
    "`yoke projects capability-secret set` can only overwrite one."
)
NO_FLOW_COMMAND = (
    "No yoke command deletes a deployment flow; retirement disabled them."
)
NO_ENVIRONMENT_COMMAND = "No yoke command removes an environment."
NO_SITE_COMMAND = "No yoke command removes a site."
NO_PACK_COMMAND = (
    "No yoke command removes recorded Pack installs; they mirror the "
    "checkout's Pack receipt."
)
NO_ROLE_COMMAND = "No yoke command revokes a project role grant."
NO_PULUMI_COMMAND = (
    "No yoke command removes Pulumi stack state; it lives in the pulumi-state "
    "capability or in site settings."
)


def _entry(kind, count, *, label, commands=(), names=(), no_command=None, partial=False):
    """``partial`` keeps ``no_command`` when only some records have a command."""
    shown = bool(count) and (partial or not commands)
    return {
        "kind": kind,
        "label": label,
        "count": count,
        "names": list(names),
        "commands": list(commands),
        "no_command": no_command if shown else None,
    }


def remaining_attachments(conn: Any, project_id: int) -> list[dict[str, Any]]:
    """Return one entry per attached kind, stored credentials first."""
    slug = conn.execute(
        "SELECT slug FROM projects WHERE id=%s", (project_id,)
    ).fetchone()[0]
    q = shlex.quote
    proj = q(slug)
    secrets = query_rows(
        conn,
        "SELECT type, key FROM capability_secrets WHERE project_id=%s "
        "ORDER BY type, key",
        (project_id,),
    )
    capabilities = [
        str(row["type"])
        for row in query_rows(
            conn,
            "SELECT type FROM project_capabilities WHERE project_id=%s ORDER BY type",
            (project_id,),
        )
    ]
    binding = conn.execute(
        "SELECT github_repo FROM project_github_repo_bindings WHERE project_id=%s",
        (project_id,),
    ).fetchone()
    flows = _ids(conn, "SELECT id FROM deployment_flows WHERE project_id=%s ORDER BY id", project_id)
    plans = query_rows(
        conn,
        "SELECT slug, retired_at FROM qa_plans WHERE project_id=%s ORDER BY slug",
        (project_id,),
    )
    defaults = query_rows(
        conn,
        "SELECT plan_id, workflow_id, transition_id FROM qa_plan_project_defaults "
        "WHERE project_id=%s ORDER BY plan_id, workflow_id, transition_id",
        (project_id,),
    )
    return [
        _entry(
            "capability_secrets",
            len(secrets),
            label="stored credentials",
            names=[f"{row['type']}.{row['key']}" for row in secrets],
            no_command=NO_SECRET_COMMAND,
        ),
        _entry(
            "capability_settings",
            len(capabilities),
            label="capability settings",
            names=capabilities,
            commands=[c for c in (_capability_command(t, proj) for t in capabilities) if c],
            no_command=NO_PULUMI_COMMAND,
            partial=PULUMI_STATE_CAPABILITY in capabilities,
        ),
        _entry(
            "github_binding",
            int(binding is not None),
            label="GitHub repository binding",
            names=[str(binding[0])] if binding is not None else [],
            commands=(
                [f"yoke projects github-binding unbind --project {proj}"]
                if binding is not None
                else []
            ),
        ),
        _entry(
            "deployment_flows", len(flows), label="deployment flows (disabled)",
            names=flows, no_command=NO_FLOW_COMMAND,
        ),
        _counted(conn, "environments", "environments", project_id, NO_ENVIRONMENT_COMMAND),
        _counted(conn, "sites", "sites", project_id, NO_SITE_COMMAND),
        _entry(
            "pack_records",
            _count(conn, "project_pack_report_entries", project_id),
            label="Pack install records",
            names=_ids(
                conn,
                "SELECT pack_slug FROM project_pack_report_entries "
                "WHERE project_id=%s ORDER BY pack_slug",
                project_id,
            ),
            no_command=NO_PACK_COMMAND,
        ),
        _entry(
            "qa_plans",
            len(plans),
            label="QA plans",
            names=[str(row["slug"]) for row in plans],
            commands=[
                f"yoke qa plan retire {q(str(row['slug']))} --project {proj} "
                "--reason 'Project retired'"
                for row in plans
                if row["retired_at"] is None
            ],
            no_command="Every QA plan is already retired; no command deletes one.",
        ),
        _entry(
            "qa_plan_defaults",
            len(defaults),
            label="QA plan project defaults",
            commands=[
                f"yoke qa project-default unset --project {proj} "
                f"--plan-id {row['plan_id']} --workflow {q(str(row['workflow_id']))} "
                f"--transition {q(str(row['transition_id']))}"
                for row in defaults
            ],
        ),
        _counted(conn, "project_roles", "actor_project_roles", project_id, NO_ROLE_COMMAND),
        _entry(
            "pulumi_stack_state",
            int(_pulumi_stack_state_present(conn, project_id)),
            label="Pulumi stack state",
            no_command=NO_PULUMI_COMMAND,
        ),
    ]


def _capability_command(cap_type: str, proj: str) -> str | None:
    q = shlex.quote
    if cap_type == GITHUB_CAPABILITY_TYPE:
        return f"yoke projects github-binding unbind --project {proj}"
    if cap_type == PULUMI_STATE_CAPABILITY:
        return None
    if cap_type.startswith("test-machine:"):
        name = cap_type.split(":", 1)[1]
        return (
            f"yoke test-machine delete --project {proj} "
            f"--test-machine {q(name)} --confirm"
        )
    get = f"yoke projects capability-settings get --project {proj} --cap-type {q(cap_type)}"
    return (
        f"yoke projects capability-settings remove --project {proj} "
        f'--cap-type {q(cap_type)} --base "$({get})"'
    )


def _counted(conn, kind, table, project_id, no_command):
    return _entry(
        kind,
        _count(conn, table, project_id),
        label=kind.replace("_", " "),
        no_command=no_command,
    )


def _count(conn: Any, table: str, project_id: int) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE project_id=%s", (project_id,)
    ).fetchone()
    return int(row[0] or 0)


def _ids(conn: Any, sql: str, project_id: int) -> list[str]:
    return [str(row[0]) for row in conn.execute(sql, (project_id,)).fetchall()]


def _pulumi_stack_state_present(conn: Any, project_id: int) -> bool:
    """Stack state lives in the pulumi-state capability or legacy site settings."""
    capability = conn.execute(
        "SELECT settings FROM project_capabilities WHERE project_id=%s AND type=%s",
        (project_id, PULUMI_STATE_CAPABILITY),
    ).fetchone()
    if capability is not None and _json(capability[0]).get(STACK_STATE_KEY):
        return True
    for row in conn.execute(
        "SELECT settings FROM sites WHERE project_id=%s", (project_id,)
    ).fetchall():
        pulumi = _json(row[0]).get("pulumi")
        if isinstance(pulumi, dict) and pulumi.get("stack_state"):
            return True
    return False


def _json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


__all__ = ["remaining_attachments"]
