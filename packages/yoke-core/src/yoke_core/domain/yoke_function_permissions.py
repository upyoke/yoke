"""Project-role permission checks for Yoke function dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.actor_permissions import (
    PERM_DB_READ_RAW,
    PERM_ITEMS_READ,
    PermissionDenied,
    require_org_permission,
    require_permission,
)
from yoke_core.domain.actor_project_visibility import (
    actor_project_ids_with_permission,
)
from yoke_core.domain.function_authz_scope import (
    ACTOR_SESSION,
    CLIENT_LOCAL,
    CONTROL_PLANE,
    DENY,
    ORG,
    classify,
    permission_key_for,
)
from yoke_core.domain.function_target_resolution import (
    resolve_org_context,
    resolve_project_context,
)
from yoke_core.domain.project_identity import AmbiguousProjectRefError, resolve_project_id
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)
from yoke_core.domain.yoke_function_registry import RegistryEntry


@dataclass(frozen=True)
class DispatchPermission:
    permission_key: str | None
    project_id: int | None
    project_slug: str | None
    visible_project_ids: tuple[int, ...] | None = None
    error: FunctionCallResponse | None = None


def check_dispatch_permission(
    conn: Any,
    entry: RegistryEntry,
    request: FunctionCallRequest,
) -> DispatchPermission:
    """Authorize one function call against the token-verified actor identity."""
    spec = classify(
        entry.function_id,
        side_effects=bool(entry.side_effects),
        project_permission=permission_key_for(entry),
    )
    if spec.scope == CLIENT_LOCAL:
        return DispatchPermission(spec.permission_key, None, None)
    actor_id = _numeric_actor_id(request.actor.actor_id)
    if actor_id is None:
        return DispatchPermission(spec.permission_key, None, None)
    if entry.function_id == "doctor.run.run":
        return _doctor_dispatch_permission(conn, entry, request, actor_id)
    if entry.function_id == "board.data.get":
        return _board_data_get_dispatch_permission(
            conn, entry, request, actor_id, spec.permission_key or PERM_ITEMS_READ,
        )
    if spec.scope == DENY:
        return DispatchPermission(
            spec.permission_key, None, None,
            error=_error_response(
                request, entry, "permission_denied",
                f"function {entry.function_id!r} has side effects but is not "
                "classified for authorization; denied by default",
            ),
        )
    if spec.scope == ACTOR_SESSION:
        return DispatchPermission(spec.permission_key, None, None)
    if spec.scope == CONTROL_PLANE:
        project_id = resolve_project_id(conn, "yoke")
        project_slug = "yoke"
    elif spec.scope == ORG:
        org_id = resolve_org_context(conn, request)
        if org_id is None:
            return DispatchPermission(
                spec.permission_key, None, None,
                error=_error_response(
                    request, entry, "permission_denied",
                    "could not resolve a target org for an org-scoped function",
                ),
            )
        try:
            require_org_permission(
                conn, actor_id=actor_id, org_id=org_id,
                permission_key=spec.permission_key,
            )
        except PermissionDenied as exc:
            return DispatchPermission(
                spec.permission_key, None, None,
                error=_error_response(request, entry, "permission_denied", str(exc)),
            )
        return DispatchPermission(spec.permission_key, None, None)
    else:  # PROJECT
        visible_ids = actor_project_ids_with_permission(
            conn, actor_id, spec.permission_key or PERM_ITEMS_READ,
        )
        try:
            project_context = resolve_project_context(
                conn, entry, request, visible_project_ids=visible_ids,
        )
        except AmbiguousProjectRefError as exc:
            return DispatchPermission(
                spec.permission_key, None, None,
                error=_error_response(request, entry, "ambiguous_project", str(exc)),
            )
        if project_context is None:
            return DispatchPermission(spec.permission_key, None, None)
        project_id, project_slug = project_context
    try:
        require_permission(
            conn, actor_id=actor_id, project_id=project_id,
            permission_key=spec.permission_key,
        )
    except PermissionDenied as exc:
        return DispatchPermission(
            spec.permission_key, project_id, project_slug,
            error=_error_response(request, entry, "permission_denied", str(exc)),
        )
    return DispatchPermission(spec.permission_key, project_id, project_slug)


def _board_data_get_dispatch_permission(
    conn: Any,
    entry: RegistryEntry,
    request: FunctionCallRequest,
    actor_id: int,
    permission_key: str,
) -> DispatchPermission:
    visible_ids = actor_project_ids_with_permission(
        conn, actor_id, permission_key,
    )
    ordered_visible = tuple(sorted(visible_ids or ()))
    scope = str((request.payload or {}).get("scope") or "all").strip() or "all"
    if scope == "all":
        if not ordered_visible:
            return DispatchPermission(
                permission_key, None, "all",
                visible_project_ids=ordered_visible,
                error=_error_response(
                    request, entry, "permission_denied",
                    f"actor {actor_id} lacks {permission_key!r} on any project",
                ),
            )
        return DispatchPermission(
            permission_key, None, "all",
            visible_project_ids=ordered_visible,
        )

    try:
        project_context = resolve_project_context(
            conn, entry, request, visible_project_ids=visible_ids,
        )
    except AmbiguousProjectRefError as exc:
        return DispatchPermission(
            permission_key, None, None,
            visible_project_ids=ordered_visible,
            error=_error_response(request, entry, "ambiguous_project", str(exc)),
        )
    if project_context is None:
        return DispatchPermission(
            permission_key, None, None,
            visible_project_ids=ordered_visible,
            error=_error_response(
                request, entry, "permission_denied",
                "could not resolve a target project for project-scoped function",
            ),
        )
    project_id, project_slug = project_context
    try:
        require_permission(
            conn, actor_id=actor_id, project_id=project_id,
            permission_key=permission_key,
        )
    except PermissionDenied as exc:
        return DispatchPermission(
            permission_key, project_id, project_slug,
            visible_project_ids=ordered_visible,
            error=_error_response(request, entry, "permission_denied", str(exc)),
        )
    return DispatchPermission(
        permission_key, project_id, project_slug,
        visible_project_ids=ordered_visible,
    )


def _doctor_dispatch_permission(
    conn: Any,
    entry: RegistryEntry,
    request: FunctionCallRequest,
    actor_id: int,
) -> DispatchPermission:
    if _is_project_safe_doctor_quick(request.payload):
        visible_ids = actor_project_ids_with_permission(conn, actor_id, PERM_ITEMS_READ)
        try:
            project_context = resolve_project_context(
                conn, entry, request, visible_project_ids=visible_ids,
            )
        except AmbiguousProjectRefError as exc:
            return DispatchPermission(
                PERM_ITEMS_READ, None, None,
                error=_error_response(request, entry, "ambiguous_project", str(exc)),
            )
        if project_context is None:
            return DispatchPermission(
                PERM_ITEMS_READ, None, None,
                error=_error_response(
                    request, entry, "permission_denied",
                    "could not resolve a target project for project-scoped doctor",
                ),
            )
        project_id, project_slug = project_context
        try:
            require_permission(
                conn, actor_id=actor_id, project_id=project_id,
                permission_key=PERM_ITEMS_READ,
            )
        except PermissionDenied as exc:
            return DispatchPermission(
                PERM_ITEMS_READ, project_id, project_slug,
                error=_error_response(request, entry, "permission_denied", str(exc)),
            )
        return DispatchPermission(PERM_ITEMS_READ, project_id, project_slug)

    project_id = resolve_project_id(conn, "yoke")
    try:
        require_permission(
            conn, actor_id=actor_id, project_id=project_id,
            permission_key=PERM_DB_READ_RAW,
        )
    except PermissionDenied as exc:
        return DispatchPermission(
            PERM_DB_READ_RAW, project_id, "yoke",
            error=_error_response(request, entry, "permission_denied", str(exc)),
        )
    return DispatchPermission(PERM_DB_READ_RAW, project_id, "yoke")


def _is_project_safe_doctor_quick(payload: dict[str, Any] | None) -> bool:
    payload = payload or {}
    return (
        payload.get("quick") is True
        and not any(payload.get(key) for key in ("full", "only", "fix", "db_path"))
        and payload.get("skip_source_tree_checks") is True
    )


def dispatch_permission_for_request(
    entry: RegistryEntry,
    request: FunctionCallRequest,
) -> DispatchPermission:
    """Authorize one dispatcher request against the token-verified actor."""
    spec = classify(
        entry.function_id,
        side_effects=bool(entry.side_effects),
        project_permission=permission_key_for(entry),
    )
    if spec.scope == CLIENT_LOCAL:
        return DispatchPermission(spec.permission_key, None, None)
    if _numeric_actor_id(request.actor.actor_id) is None:
        return DispatchPermission(spec.permission_key, None, None)
    if spec.scope == DENY:
        return DispatchPermission(
            spec.permission_key, None, None,
            error=_error_response(
                request, entry, "permission_denied",
                f"function {entry.function_id!r} has side effects but is not "
                "classified for authorization; denied by default",
            ),
        )
    try:
        from yoke_core.domain import db_helpers

        with db_helpers.connect() as conn:
            return check_dispatch_permission(conn, entry, request)
    except db_backend.database_error_types() as exc:
        return DispatchPermission(
            spec.permission_key,
            None,
            None,
            error=_error_response(
                request,
                entry,
                "permission_check_unavailable",
                f"permission check failed before handler dispatch: {exc}",
            ),
        )


def _numeric_actor_id(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or not text.isdigit():
        return None
    return int(text)


def _error_response(
    request: FunctionCallRequest,
    entry: RegistryEntry,
    code: str,
    message: str,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=entry.function_id,
        version=entry.version,
        request_id=request.request_id,
        result={},
        warnings=[],
        error=FunctionError(code=code, message=message),
        event_ids=[],
    )


__all__ = [
    "DispatchPermission",
    "check_dispatch_permission",
    "dispatch_permission_for_request",
    "permission_key_for",
]
