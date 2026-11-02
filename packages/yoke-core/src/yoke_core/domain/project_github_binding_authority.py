"""Hosted GitHub bindings require the host's installation-ownership checks."""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain import db_backend
from yoke_core.domain.function_unresolved_project import permission_error_response
from yoke_core.domain.hosted_service_authority import (
    HOSTED_SERVICE_COMPONENT,
    PERM_HOSTED_SERVICE_DELIVER,
    hosted_service_org_ids,
)
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.yoke_function_permission_types import DispatchPermission
from yoke_core.domain.yoke_function_registry import RegistryEntry


def hosted_binding_permission(
    conn: Any,
    entry: RegistryEntry,
    request: FunctionCallRequest,
    actor_id: int | None,
) -> DispatchPermission | None:
    """Leave standalone binds alone; authorize hosted binds for the actual org."""
    if entry.function_id != "projects.github_binding.bind":
        return None
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    hosted = conn.execute(
        "SELECT 1 FROM actors WHERE kind = 'system' "
        f"AND system_component = {p} LIMIT 1",
        (HOSTED_SERVICE_COMPONENT,),
    ).fetchone()
    if hosted is None:
        return None

    org_ids = hosted_service_org_ids(conn, actor_id) if actor_id is not None else ()
    if org_ids:
        # The handler acts on payload.project. A target or payload org must
        # never authorize a different project than the one it will bind.
        try:
            project = resolve_project(
                conn, str(request.payload.get("project") or ""), required=True
            )
        except (LookupError, ValueError):
            project = None
        if project is not None:
            row = conn.execute(
                f"SELECT org_id FROM projects WHERE id = {p}", (project.id,)
            ).fetchone()
            if row is not None and row[0] in org_ids:
                return DispatchPermission(
                    PERM_HOSTED_SERVICE_DELIVER, project.id, project.slug
                )

    return DispatchPermission(
        PERM_HOSTED_SERVICE_DELIVER,
        None,
        None,
        error=permission_error_response(
            request,
            entry,
            "github_binding_hosted_only",
            compose_refusal(
                "Hosted GitHub bindings require the hosted service identity "
                "for the project's org after installation-ownership checks.",
                recovery="bind through the hosted org using `yoke projects "
                "github-binding bind` or `yoke onboard` (the CLI routes "
                "automatically), or choose Connect GitHub on the org's GitHub page.",
            ),
        ),
    )
