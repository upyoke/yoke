"""Registered-function handlers for the session-launch lifecycle."""

from __future__ import annotations

from yoke_contracts.fleet_policy import (
    LAUNCH_DEADLINE_MINUTES,
    MAX_BODY_BYTES,
    SURFACE_FALLBACK,
)

from typing import Any

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.session_control.models import (
    LaunchCreateRequest,
    LaunchListRequest,
    LaunchMutationRequest,
    LaunchPreviewRequest,
    LaunchReconcileRequest,
)
from yoke_core.domain.session_launch_types import (
    LaunchAuthorization,
    SessionLaunchError,
)
from yoke_core.domain.session_launch_projection import public_launch_record
from yoke_core.domain.session_launch_validation import require_launch_id


def _failure(code: str, message: str, path: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=path),
    )


def _parse(model: Any, request: FunctionCallRequest) -> Any:
    try:
        return model.model_validate(request.payload or {})
    except Exception as exc:
        return _failure("payload_invalid", str(exc))


def _actor_id(request: FunctionCallRequest) -> int:
    raw = str(request.actor.actor_id or "").strip()
    if not raw.isdigit():
        raise SessionLaunchError("actor_required", "verified numeric actor is required")
    return int(raw)


def launch_authorization(
    conn: Any,
    request: FunctionCallRequest,
    project_id: int,
) -> LaunchAuthorization:
    """The caller's launch authority in one project, as every launch reads it."""
    from yoke_core.domain.session_control_request_identity import (
        registered_request_session_id,
    )
    from yoke_core.domain.session_launch_authorization import launch_authorization

    return launch_authorization(
        conn,
        actor_id=_actor_id(request),
        project_id=project_id,
        session_id=registered_request_session_id(conn, request.actor.session_id),
    )


def _resolve_project(conn: Any, project: str) -> int:
    from yoke_core.domain.project_identity import resolve_project_id

    return resolve_project_id(conn, project)


def _open() -> Any:
    from yoke_core.domain.db_helpers import connect

    return connect()


def _domain_error(exc: Exception) -> HandlerOutcome:
    if isinstance(exc, SessionLaunchError):
        return _failure(exc.code, str(exc))
    if isinstance(exc, LookupError):
        return _failure("not_found", str(exc))
    return _failure("launch_rejected", str(exc))


def handle_launch_preview(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = _parse(LaunchPreviewRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    from yoke_core.domain.session_launch_preview_payload import (
        explicit_preview_payload,
        level_preview_payload,
    )

    conn = _open()
    try:
        project_id = _resolve_project(conn, parsed.project)
        auth = launch_authorization(conn, request, project_id)
        if parsed.level:
            payload = level_preview_payload(
                conn, auth=auth, project_id=project_id, level=parsed.level
            )
        else:
            payload = explicit_preview_payload(
                conn,
                auth=auth,
                project_id=project_id,
                parsed=parsed,
                surface_fallback_enabled=SURFACE_FALLBACK,
            )
        return HandlerOutcome(result_payload=payload)
    except Exception as exc:
        return _domain_error(exc)
    finally:
        conn.close()


def handle_launch_create(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = _parse(LaunchCreateRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    from yoke_core.domain.session_launch_mandate import launch_request_for_create
    from yoke_core.domain.session_launch_requests import create_launch

    conn = _open()
    try:
        project_id = _resolve_project(conn, parsed.project)
        deadline_seconds = LAUNCH_DEADLINE_MINUTES * 60
        max_body_bytes = MAX_BODY_BYTES
        auth = launch_authorization(conn, request, project_id)
        outcome = create_launch(
            conn,
            auth=auth,
            request=launch_request_for_create(
                conn,
                parsed,
                project_id=project_id,
                deadline_seconds=deadline_seconds,
                actor_id=auth.actor_id,
                session_id=auth.session_id,
            ),
            max_body_bytes=max_body_bytes,
            surface_fallback_enabled=SURFACE_FALLBACK,
        )
        return HandlerOutcome(
            result_payload={
                "launch": public_launch_record(outcome.launch),
                "preview": outcome.preview.to_dict(),
                "deduplicated": outcome.deduplicated,
                "item_level": outcome.item_level,
            }
        )
    except Exception as exc:
        return _domain_error(exc)
    finally:
        conn.close()


def _launch_and_auth(conn: Any, request: FunctionCallRequest, launch_id: str):
    from yoke_core.domain.session_launch_deadlines import settle_launch_deadlines
    from yoke_core.domain.session_launch_store import get_launch

    settle_launch_deadlines(conn, launch_id=launch_id)
    launch = get_launch(conn, launch_id)
    return launch, launch_authorization(conn, request, launch.project_id)


def handle_launch_get(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = _parse(LaunchMutationRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    try:
        launch_id = require_launch_id(parsed.launch_id)
    except SessionLaunchError as exc:
        return _domain_error(exc)
    conn = _open()
    try:
        launch, auth = _launch_and_auth(conn, request, launch_id)
        if not auth.can_operate_project:
            raise SessionLaunchError("permission_denied", "project operator required")
        return HandlerOutcome(result_payload={"launch": public_launch_record(launch)})
    except Exception as exc:
        return _domain_error(exc)
    finally:
        conn.close()


def handle_launch_list(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = _parse(LaunchListRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    from yoke_core.domain.session_launch_deadlines import settle_launch_deadlines
    from yoke_core.domain.session_launch_history_page import read_launch_page

    conn = _open()
    try:
        project_id = _resolve_project(conn, parsed.project)
        auth = launch_authorization(conn, request, project_id)
        if not auth.can_operate_project:
            raise SessionLaunchError("permission_denied", "project operator required")
        settle_launch_deadlines(conn, project_id=project_id)
        return HandlerOutcome(
            result_payload=read_launch_page(
                conn,
                project_id=project_id,
                state=parsed.state,
                surface=parsed.surface,
                machine=parsed.machine,
                limit=parsed.limit,
                cursor=parsed.cursor,
            )
        )
    except Exception as exc:
        return _domain_error(exc)
    finally:
        conn.close()


def _mutate(request: FunctionCallRequest, model: Any, operation: str) -> HandlerOutcome:
    parsed = _parse(model, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    conn = _open()
    try:
        launch_record, auth = _launch_and_auth(conn, request, parsed.launch_id)
        if operation == "cancel":
            from yoke_core.domain.session_launch_requests import cancel_launch

            launch = cancel_launch(conn, launch_id=parsed.launch_id, auth=auth)
        elif operation == "retry":
            from yoke_core.domain.session_launch_requests import retry_launch

            launch = retry_launch(
                conn,
                launch_id=parsed.launch_id,
                auth=auth,
                deadline_seconds=LAUNCH_DEADLINE_MINUTES * 60,
                surface_fallback_enabled=SURFACE_FALLBACK,
            )
        else:
            from yoke_core.domain.session_launch_execution import reconcile_launch

            launch = reconcile_launch(
                conn,
                launch_id=parsed.launch_id,
                auth=auth,
                observed_native_id=parsed.observed_native_id,
            )
        return HandlerOutcome(result_payload={"launch": public_launch_record(launch)})
    except Exception as exc:
        return _domain_error(exc)
    finally:
        conn.close()


def handle_launch_cancel(request: FunctionCallRequest) -> HandlerOutcome:
    return _mutate(request, LaunchMutationRequest, "cancel")


def handle_launch_retry(request: FunctionCallRequest) -> HandlerOutcome:
    return _mutate(request, LaunchMutationRequest, "retry")


def handle_launch_reconcile(request: FunctionCallRequest) -> HandlerOutcome:
    return _mutate(request, LaunchReconcileRequest, "reconcile")


__all__ = [
    "handle_launch_cancel",
    "handle_launch_create",
    "handle_launch_get",
    "handle_launch_list",
    "handle_launch_preview",
    "handle_launch_reconcile",
    "handle_launch_retry",
    "launch_authorization",
]
