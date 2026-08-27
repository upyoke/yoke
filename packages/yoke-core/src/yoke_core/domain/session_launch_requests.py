"""Preview, create, cancel, and retry operations for session launches."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_surface_selection import preview_launch
from yoke_core.domain.session_launch_validation import validate_launch_request
from yoke_core.domain.session_launch_store import (
    add_seconds,
    begin_mutation,
    delete_message,
    get_launch,
    get_launch_by_dedupe,
    insert_instruction_message,
    instruction_message,
    marker,
    sha256_text,
    update_launch,
    utc_now,
)
from yoke_core.domain.session_launch_types import (
    DEFAULT_LAUNCH_DEADLINE_SECONDS,
    DEFAULT_MAX_BODY_BYTES,
    LaunchAuthorization,
    LaunchCreateOutcome,
    LaunchEligibilityPort,
    LaunchPreview,
    LaunchRecord,
    LaunchRequest,
    MAX_LAUNCH_DEADLINE_SECONDS,
    SessionLaunchError,
    ensure_operator,
)


def _same_request(conn: Any, launch: LaunchRecord, request: LaunchRequest) -> bool:
    body, body_hash, _ = instruction_message(conn, launch.message_id)
    return all(
        (
            launch.project_id == request.project_id,
            launch.requested_surface == request.executor_surface,
            launch.requested_machine_id == request.machine_id,
            launch.requested_model == request.model,
            launch.presentation_preference == request.presentation,
            launch.allow_surface_fallback == request.allow_surface_fallback,
            launch.origin == request.origin,
            body_hash == sha256_text(request.instructions),
            body == request.instructions,
        )
    )


def _deduplicated(
    conn: Any,
    *,
    existing: LaunchRecord,
    request: LaunchRequest,
    preview: LaunchPreview,
) -> LaunchCreateOutcome:
    if not _same_request(conn, existing, request):
        raise SessionLaunchError(
            "idempotency_conflict",
            "idempotency key already names a different launch request",
        )
    return LaunchCreateOutcome(existing, preview, True)


def _insert_launch(
    conn: Any,
    *,
    launch_id: str,
    message_id: str,
    auth: LaunchAuthorization,
    request: LaunchRequest,
    preview: LaunchPreview,
    created_at: str,
    deadline_at: str,
) -> bool:
    relay = preview.selected_relay
    assert relay is not None
    p = marker(conn)
    columns = (
        "launch_id, requester_actor_id, requester_session_id, project_id, "
        "requested_surface, selected_surface, requested_machine_id, requested_model, "
        "presentation_preference, allow_surface_fallback, message_id, "
        "idempotency_key, state, assigned_relay_id, assigned_machine_id, "
        "deadline_at, created_at, assigned_at, origin"
    )
    values = (
        launch_id,
        auth.actor_id,
        auth.session_id,
        request.project_id,
        request.executor_surface,
        relay.surface,
        request.machine_id,
        request.model,
        request.presentation,
        int(request.allow_surface_fallback),
        message_id,
        request.idempotency_key,
        "assigned",
        relay.relay_id,
        relay.machine_id,
        deadline_at,
        created_at,
        created_at,
        request.origin,
    )
    row = conn.execute(
        f"INSERT INTO session_launches ({columns}) "
        f"VALUES ({', '.join(p for _ in values)}) "
        "ON CONFLICT DO NOTHING RETURNING launch_id",
        values,
    ).fetchone()
    return row is not None


def create_launch(
    conn: Any,
    *,
    auth: LaunchAuthorization,
    request: LaunchRequest,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    surface_fallback_enabled: bool = False,
    auto_select_machine: bool = False,
    now: str | None = None,
    eligibility: LaunchEligibilityPort = derive_launch_eligibility,
) -> LaunchCreateOutcome:
    """Persist one instruction message and an assigned launch atomically."""
    ensure_operator(auth)
    validate_launch_request(request, max_body_bytes=max_body_bytes)
    current = now or utc_now()
    begin_mutation(conn)
    try:
        existing = get_launch_by_dedupe(conn, auth.actor_id, request.idempotency_key)
        preview = preview_launch(
            conn,
            auth=auth,
            project_id=request.project_id,
            surface=request.executor_surface,
            machine_id=request.machine_id,
            allow_surface_fallback=request.allow_surface_fallback,
            surface_fallback_enabled=surface_fallback_enabled,
            auto_select_machine=auto_select_machine,
            now=current,
            eligibility=eligibility,
        )
        if existing is not None:
            outcome = _deduplicated(
                conn,
                existing=existing,
                request=request,
                preview=preview,
            )
            conn.commit()
            return outcome
        if not preview.launchable:
            from yoke_core.domain.session_surface_policy import launch_refusal_message

            raise SessionLaunchError(
                preview.outcome, launch_refusal_message(conn, preview)
            )

        launch_id = str(uuid4())
        message_id = str(uuid4())
        deadline_at = add_seconds(current, request.deadline_seconds)
        insert_instruction_message(
            conn,
            message_id=message_id,
            launch_id=launch_id,
            actor_id=auth.actor_id,
            session_id=auth.session_id,
            project_id=request.project_id,
            body=request.instructions,
            created_at=current,
            expires_at=deadline_at,
        )
        inserted = _insert_launch(
            conn,
            launch_id=launch_id,
            message_id=message_id,
            auth=auth,
            request=request,
            preview=preview,
            created_at=current,
            deadline_at=deadline_at,
        )
        if not inserted:
            delete_message(conn, message_id)
            existing = get_launch_by_dedupe(
                conn,
                auth.actor_id,
                request.idempotency_key,
            )
            if existing is None:
                raise SessionLaunchError("create_conflict", "launch insert conflicted")
            outcome = _deduplicated(
                conn,
                existing=existing,
                request=request,
                preview=preview,
            )
            conn.commit()
            return outcome
        launch = get_launch(conn, launch_id)
        conn.commit()
        return LaunchCreateOutcome(launch, preview, False)
    except Exception:
        conn.rollback()
        raise


def cancel_launch(
    conn: Any,
    *,
    launch_id: str,
    auth: LaunchAuthorization,
    now: str | None = None,
) -> LaunchRecord:
    current = now or utc_now()
    begin_mutation(conn)
    try:
        launch = get_launch(conn, launch_id, for_update=True)
        if (
            auth.actor_id != launch.requester_actor_id
            and not auth.can_administer_project
        ):
            raise SessionLaunchError(
                "permission_denied",
                "only the requester or project admin may cancel",
            )
        if launch.state == "cancelled":
            conn.commit()
            return launch
        if launch.state == "succeeded":
            raise SessionLaunchError(
                "invalid_state", "a succeeded launch cannot be cancelled"
            )
        if launch.state in {"launching", "outcome_unknown"}:
            result = update_launch(
                conn,
                launch_id,
                delivery_changed_at=current,
                state="outcome_unknown",
                result_code="cancellation_requires_reconciliation",
            )
        else:
            result = update_launch(
                conn,
                launch_id,
                state="cancelled",
                completed_at=current,
                result_code=(
                    "cancelled_after_native_create"
                    if launch.native_session_id
                    else "cancelled"
                ),
            )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def retry_launch(
    conn: Any,
    *,
    launch_id: str,
    auth: LaunchAuthorization,
    deadline_seconds: int = DEFAULT_LAUNCH_DEADLINE_SECONDS,
    surface_fallback_enabled: bool = False,
    auto_select_machine: bool = False,
    now: str | None = None,
    eligibility: LaunchEligibilityPort = derive_launch_eligibility,
) -> LaunchRecord:
    ensure_operator(auth)
    if not 60 <= deadline_seconds <= MAX_LAUNCH_DEADLINE_SECONDS:
        raise SessionLaunchError("deadline_invalid", "retry deadline is out of bounds")
    current = now or utc_now()
    begin_mutation(conn)
    try:
        launch = get_launch(conn, launch_id, for_update=True)
        if launch.state == "outcome_unknown" or launch.native_session_id:
            raise SessionLaunchError(
                "reconcile_required",
                "reconcile possible native creation before retry",
            )
        if launch.state not in {"failed", "expired"}:
            raise SessionLaunchError(
                "invalid_state",
                f"launch in state {launch.state!r} cannot be retried",
            )
        preview = preview_launch(
            conn,
            auth=auth,
            project_id=launch.project_id,
            surface=launch.requested_surface,
            machine_id=launch.requested_machine_id,
            allow_surface_fallback=launch.allow_surface_fallback,
            surface_fallback_enabled=surface_fallback_enabled,
            auto_select_machine=auto_select_machine,
            now=current,
            eligibility=eligibility,
        )
        if not preview.launchable:
            raise SessionLaunchError(preview.outcome, "no relay is eligible for retry")
        relay = preview.selected_relay
        assert relay is not None
        result = update_launch(
            conn,
            launch_id,
            state="assigned",
            selected_surface=relay.surface,
            assigned_relay_id=relay.relay_id,
            assigned_machine_id=relay.machine_id,
            native_session_id=None,
            attestation_hash=None,
            attestation_consumed_at=None,
            registered_session_id=None,
            deadline_at=add_seconds(current, deadline_seconds),
            assigned_at=current,
            launching_at=None,
            awaiting_registration_at=None,
            completed_at=None,
            result_code=None,
            result_evidence=None,
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


__all__ = [
    "cancel_launch",
    "create_launch",
    "preview_launch",
    "retry_launch",
]
