"""Registered-function handlers for the session-launch lifecycle."""

from __future__ import annotations

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
from yoke_core.domain.session_launch_projection import (
    public_launch_record,
    public_launch_records,
)
from yoke_core.domain.session_launch_validation import preview_model_selection_payload
from yoke_core.domain.session_launch_validation import validate_preview_model_selection


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


def _authorization(
    conn: Any,
    request: FunctionCallRequest,
    project_id: int,
) -> LaunchAuthorization:
    from yoke_core.domain.actor_permissions import (
        PERM_ITEMS_WRITE,
        PERM_PROJECT_ADMIN,
        permission_decision,
    )
    from yoke_core.domain.session_control_request_identity import (
        registered_request_session_id,
    )

    actor_id = _actor_id(request)
    operate = permission_decision(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        permission_key=PERM_ITEMS_WRITE,
    ).allowed
    administer = permission_decision(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        permission_key=PERM_PROJECT_ADMIN,
    ).allowed
    return LaunchAuthorization(
        actor_id=actor_id,
        session_id=registered_request_session_id(
            conn,
            request.actor.session_id,
        ),
        can_operate_project=operate,
        can_administer_project=administer,
    )


def _resolve_project(conn: Any, project: str) -> int:
    from yoke_core.domain.project_identity import resolve_project_id

    return resolve_project_id(conn, project)


def _fleet_policy(conn: Any, project_id: int, path: str) -> Any:
    from yoke_core.domain.organization_settings import read_organization_setting
    from yoke_core.domain.session_launch_store import marker, value

    p = marker(conn)
    row = conn.execute(
        f"SELECT org_id FROM projects WHERE id = {p}",
        (project_id,),
    ).fetchone()
    if row is None:
        raise SessionLaunchError("project_not_found", "project does not exist")
    setting, _ = read_organization_setting(conn, int(value(row, "org_id", 0)), path)
    return setting


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
    from yoke_core.domain.session_launch_machine_models import (
        resolve_machine_selection,
    )
    from yoke_core.domain.session_launch_requests import preview_launch

    conn = _open()
    try:
        project_id = _resolve_project(conn, parsed.project)
        selection = validate_preview_model_selection(parsed.executor_surface, parsed)
        preview = preview_launch(
            conn,
            auth=_authorization(conn, request, project_id),
            project_id=project_id,
            surface=parsed.executor_surface,
            machine_id=parsed.machine_id,
            allow_surface_fallback=parsed.allow_surface_fallback,
            surface_fallback_enabled=bool(
                _fleet_policy(conn, project_id, "fleet.surface_fallback")
            ),
        )
        if preview.selected_surface:
            selection = validate_preview_model_selection(
                preview.selected_surface, parsed
            )
        payload = preview.to_dict()
        payload.update(preview_model_selection_payload(selection))
        relay = preview.selected_relay
        payload.update(
            resolve_machine_selection(
                conn,
                requested_model=parsed.model,
                requested_reasoning_effort=parsed.reasoning_effort,
                requested_context_window_tokens=parsed.context_window_tokens,
                machine_id=relay.machine_id if relay else None,
                surface=relay.surface if relay else parsed.executor_surface,
            ).to_dict()
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
    from yoke_core.domain.session_launch_assignment import assignment_session_name
    from yoke_core.domain.session_launch_mandate import launch_request_for_create
    from yoke_core.domain.session_launch_requests import create_launch

    conn = _open()
    try:
        project_id = _resolve_project(conn, parsed.project)
        deadline_seconds = (
            int(_fleet_policy(conn, project_id, "fleet.launch_deadline_minutes")) * 60
        )
        max_body_bytes = int(_fleet_policy(conn, project_id, "fleet.max_body_bytes"))
        auth = _authorization(conn, request, project_id)
        outcome = create_launch(
            conn,
            auth=auth,
            request=launch_request_for_create(
                conn,
                parsed,
                project_id=project_id,
                session_name=assignment_session_name(
                    conn, public_ref=parsed.item, project_id=project_id
                ),
                deadline_seconds=deadline_seconds,
            ),
            max_body_bytes=max_body_bytes,
            surface_fallback_enabled=bool(
                _fleet_policy(conn, project_id, "fleet.surface_fallback")
            ),
        )
        return HandlerOutcome(
            result_payload={
                "launch": public_launch_record(outcome.launch),
                "preview": outcome.preview.to_dict(),
                "deduplicated": outcome.deduplicated,
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
    return launch, _authorization(conn, request, launch.project_id)


def handle_launch_get(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = _parse(LaunchMutationRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    conn = _open()
    try:
        launch, auth = _launch_and_auth(conn, request, parsed.launch_id)
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
    from yoke_core.domain.session_launch_store import list_launches

    conn = _open()
    try:
        project_id = _resolve_project(conn, parsed.project)
        auth = _authorization(conn, request, project_id)
        if not auth.can_operate_project:
            raise SessionLaunchError("permission_denied", "project operator required")
        settle_launch_deadlines(conn, project_id=project_id)
        rows = public_launch_records(
            list_launches(
                conn,
                project_id=project_id,
                state=parsed.state,
                limit=parsed.limit,
            )
        )
        return HandlerOutcome(result_payload={"launches": rows, "count": len(rows)})
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
                deadline_seconds=int(
                    _fleet_policy(
                        conn,
                        launch_record.project_id,
                        "fleet.launch_deadline_minutes",
                    )
                )
                * 60,
                surface_fallback_enabled=bool(
                    _fleet_policy(
                        conn,
                        launch_record.project_id,
                        "fleet.surface_fallback",
                    )
                ),
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
]
