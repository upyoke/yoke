"""Permission resolution for functions that need a per-function rule.

Most function ids answer "who may call this?" from their family's declared
scope (:mod:`yoke_core.domain.function_authz_scope`). A few cannot: the
board read widens or narrows with the caller's visible projects, and
doctor changes scope with the flags it was given — a project-safe quick
run is an ordinary project read, while anything broader is a whole-DB
diagnostic. Their resolvers live here so
:mod:`yoke_core.domain.yoke_function_permissions` keeps the shared
routing path inside the authored-file cap.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.actor_permissions import (
    PERM_DB_READ_RAW,
    PERM_ITEMS_READ,
    PermissionDenied,
    require_permission,
)
from yoke_core.domain.actor_project_visibility import actor_project_ids_with_permission
from yoke_core.domain.control_plane_authority import require_control_plane_permission
from yoke_core.domain.function_target_resolution import resolve_project_context
from yoke_core.domain.function_unresolved_project import (
    permission_error_response as _error_response,
)
from yoke_core.domain.project_identity import AmbiguousProjectRefError
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.yoke_function_permission_types import DispatchPermission
from yoke_core.domain.yoke_function_registry import RegistryEntry


def board_data_get_dispatch_permission(
    conn: Any,
    entry: RegistryEntry,
    request: FunctionCallRequest,
    actor_id: int,
    permission_key: str,
) -> DispatchPermission:
    visible_ids = actor_project_ids_with_permission(
        conn,
        actor_id,
        permission_key,
    )
    ordered_visible = tuple(sorted(visible_ids or ()))
    scope = str((request.payload or {}).get("scope") or "all").strip() or "all"
    if scope == "all":
        if not ordered_visible:
            return DispatchPermission(
                permission_key,
                None,
                "all",
                visible_project_ids=ordered_visible,
                error=_error_response(
                    request,
                    entry,
                    "permission_denied",
                    f"actor {actor_id} lacks {permission_key!r} on any project",
                ),
            )
        return DispatchPermission(
            permission_key,
            None,
            "all",
            visible_project_ids=ordered_visible,
        )

    try:
        project_context = resolve_project_context(
            conn,
            entry,
            request,
            visible_project_ids=visible_ids,
        )
    except AmbiguousProjectRefError as exc:
        return DispatchPermission(
            permission_key,
            None,
            None,
            visible_project_ids=ordered_visible,
            error=_error_response(request, entry, "ambiguous_project", str(exc)),
        )
    if project_context is None:
        return DispatchPermission(
            permission_key,
            None,
            None,
            visible_project_ids=ordered_visible,
            error=_error_response(
                request,
                entry,
                "permission_denied",
                "could not resolve a target project for project-scoped function",
            ),
        )
    project_id, project_slug = project_context
    try:
        require_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission_key=permission_key,
        )
    except PermissionDenied as exc:
        return DispatchPermission(
            permission_key,
            project_id,
            project_slug,
            visible_project_ids=ordered_visible,
            error=_error_response(request, entry, "permission_denied", str(exc)),
        )
    return DispatchPermission(
        permission_key,
        project_id,
        project_slug,
        visible_project_ids=ordered_visible,
    )


def doctor_dispatch_permission(
    conn: Any,
    entry: RegistryEntry,
    request: FunctionCallRequest,
    actor_id: int,
) -> DispatchPermission:
    if _is_project_safe_doctor_quick(request.payload):
        visible_ids = actor_project_ids_with_permission(conn, actor_id, PERM_ITEMS_READ)
        try:
            project_context = resolve_project_context(
                conn,
                entry,
                request,
                visible_project_ids=visible_ids,
            )
        except AmbiguousProjectRefError as exc:
            return DispatchPermission(
                PERM_ITEMS_READ,
                None,
                None,
                error=_error_response(request, entry, "ambiguous_project", str(exc)),
            )
        if project_context is None:
            return DispatchPermission(
                PERM_ITEMS_READ,
                None,
                None,
                error=_error_response(
                    request,
                    entry,
                    "permission_denied",
                    "could not resolve a target project for project-scoped doctor",
                ),
            )
        project_id, project_slug = project_context
        try:
            require_permission(
                conn,
                actor_id=actor_id,
                project_id=project_id,
                permission_key=PERM_ITEMS_READ,
            )
        except PermissionDenied as exc:
            return DispatchPermission(
                PERM_ITEMS_READ,
                project_id,
                project_slug,
                error=_error_response(request, entry, "permission_denied", str(exc)),
            )
        return DispatchPermission(PERM_ITEMS_READ, project_id, project_slug)

    try:
        require_control_plane_permission(
            conn,
            actor_id=actor_id,
            permission_key=PERM_DB_READ_RAW,
        )
    except PermissionDenied as exc:
        return DispatchPermission(
            PERM_DB_READ_RAW,
            None,
            None,
            error=_error_response(request, entry, "permission_denied", str(exc)),
        )
    return DispatchPermission(PERM_DB_READ_RAW, None, None)


def _is_project_safe_doctor_quick(payload: dict[str, Any] | None) -> bool:
    payload = payload or {}
    return (
        payload.get("quick") is True
        and not any(payload.get(key) for key in ("full", "only", "fix", "db_path"))
        and payload.get("project_safe_quick") is True
    )


__all__ = [
    "board_data_get_dispatch_permission",
    "doctor_dispatch_permission",
]
