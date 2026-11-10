"""What retirement switches off, and what it leaves attached to the project.

Retire disables the project's active deployment flows, turns GitHub issue
sync off and marks its GitHub repository binding unavailable, all in the
caller's transaction. Nothing is deleted; ``project_retirement_attachments``
reports what stays attached. Unretire restores visibility only;
it reports what is still off and names the command that re-enables each.
"""

from __future__ import annotations

import shlex
from typing import Any

from yoke_contracts.project_contract.github_sync_mode import (
    GITHUB_SYNC_DISABLED,
    GITHUB_SYNC_ENABLED,
)
from yoke_core.domain.db_helpers import instant_parameter, query_rows, utc_now
from yoke_core.domain.deployment_flow_state import (
    FLOW_STATUS_ACTIVE,
    FLOW_STATUS_DISABLED,
)
from yoke_core.domain.project_github_binding_state import (
    BINDING_ACTIVE,
    BINDING_ERROR_PROJECT_RETIRED,
    BINDING_UNAVAILABLE,
)

UNRETIRE_NOTE = (
    "Unretire restored the project to active inventory only; it did not "
    "re-enable deployment flows, GitHub issue sync or the GitHub repository "
    "binding. Run the re_enable commands for the ones this project should "
    "use again."
)

def switch_off(conn: Any, project_id: int) -> dict[str, Any]:
    """Disable flows, sync and the binding; return what this call changed."""
    flows = query_rows(
        conn,
        "UPDATE deployment_flows SET status=%s WHERE project_id=%s AND status=%s "
        "RETURNING id",
        (FLOW_STATUS_DISABLED, project_id, FLOW_STATUS_ACTIVE),
    )
    sync = query_rows(
        conn,
        "UPDATE projects SET github_sync_mode=%s "
        "WHERE id=%s AND github_sync_mode=%s RETURNING id",
        (GITHUB_SYNC_DISABLED, project_id, GITHUB_SYNC_ENABLED),
    )
    now = instant_parameter(conn, utc_now())
    binding = query_rows(
        conn,
        "UPDATE project_github_repo_bindings SET status=%s, last_error=%s, "
        "updated_at=%s WHERE project_id=%s "
        "AND (status <> %s OR last_error IS DISTINCT FROM %s) RETURNING project_id",
        (
            BINDING_UNAVAILABLE,
            BINDING_ERROR_PROJECT_RETIRED,
            now,
            project_id,
            BINDING_UNAVAILABLE,
            BINDING_ERROR_PROJECT_RETIRED,
        ),
    )
    return {
        "deployment_flows_disabled": sorted(str(row["id"]) for row in flows),
        "github_sync_disabled": bool(sync),
        "github_binding_deactivated": bool(binding),
    }


def still_off(conn: Any, project_id: int) -> dict[str, Any]:
    """Report what unretire left off and the command that re-enables each."""
    project = conn.execute(
        "SELECT slug, name, github_sync_mode FROM projects WHERE id=%s",
        (project_id,),
    ).fetchone()
    slug, name, sync_mode = project[0], project[1], project[2]
    flows = sorted(
        str(row["id"])
        for row in query_rows(
            conn,
            "SELECT id FROM deployment_flows WHERE project_id=%s AND status=%s",
            (project_id, FLOW_STATUS_DISABLED),
        )
    )
    binding = conn.execute(
        "SELECT status FROM project_github_repo_bindings WHERE project_id=%s",
        (project_id,),
    ).fetchone()
    binding_status = None if binding is None else str(binding[0])
    commands = [
        f"yoke deployment-flows set-status {shlex.quote(flow)} active"
        for flow in flows
    ]
    if binding_status is not None and binding_status != BINDING_ACTIVE:
        commands.append(
            f"yoke projects github-binding check --project {shlex.quote(slug)}"
        )
    if sync_mode != GITHUB_SYNC_ENABLED and binding_status is not None:
        commands.append(
            f"yoke projects update --slug {shlex.quote(slug)} "
            f"--name {shlex.quote(name)} --github-sync-mode enabled"
        )
    return {
        "still_off": {
            "disabled_deployment_flows": flows,
            "github_sync_mode": sync_mode,
            "github_binding_status": binding_status,
        },
        "re_enable": commands,
        "note": UNRETIRE_NOTE,
    }


__all__ = [
    "UNRETIRE_NOTE",
    "still_off",
    "switch_off",
]
