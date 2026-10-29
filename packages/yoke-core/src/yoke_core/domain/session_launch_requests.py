"""Preview, create, cancel, and retry operations for session launches."""

from __future__ import annotations

from datetime import datetime
from yoke_contracts.timestamps import parse_instant
from typing import Any
from uuid import uuid4

from yoke_core.domain.session_capacity_claim_transfer import admit_assigned_launch
from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_idempotency import deduplicated_outcome
from yoke_core.domain.session_launch_item_level import pin_item_level
from yoke_core.domain.session_launch_level_placement import LEVEL_NO_CAPACITY
from yoke_core.domain.session_launch_level_selection import (
    preview_level_launch,
)
from yoke_core.domain import session_launch_native_progress as native_progress
from yoke_core.domain.session_launch_request_storage import (
    insert_launch_request,
    retry_request,
    stored_level_placement,
    resolve_work_launch_selection,
)
from yoke_core.domain.session_launch_surface_selection import preview_launch
from yoke_core.domain.session_launch_validation import (
    validate_launch_request,
    validate_model_selection,
)
from yoke_core.domain import session_relay_managed_presentation as managed_presentation
from yoke_core.domain.session_launch_store import (
    add_seconds,
    begin_mutation,
    delete_message,
    get_launch,
    get_launch_by_dedupe,
    insert_instruction_message,
    update_launch,
    utc_now,
)
from yoke_core.domain.session_launch_types import (
    DEFAULT_LAUNCH_DEADLINE_SECONDS,
    DEFAULT_MAX_BODY_BYTES,
    LaunchAuthorization,
    LaunchCreateOutcome,
    LaunchEligibilityPort,
    LaunchRecord,
    LaunchRequest,
    MAX_LAUNCH_DEADLINE_SECONDS,
    SessionLaunchError,
    ensure_operator,
)


def _require_active_project(conn, project_id):
    from yoke_core.domain.project_retirement import (
        project_is_retired,
        retired_project_recovery,
    )

    if project_is_retired(conn, project_id):
        raise SessionLaunchError(
            "project_retired", retired_project_recovery(project_id)
        )


def create_launch(
    conn: Any,
    *,
    auth: LaunchAuthorization,
    request: LaunchRequest,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    surface_fallback_enabled: bool = False,
    now: datetime | str | None = None,
    eligibility: LaunchEligibilityPort = derive_launch_eligibility,
) -> LaunchCreateOutcome:
    ensure_operator(auth)
    from yoke_core.domain.workflow_stage_levels import default_launch_level

    current = utc_now() if now is None else parse_instant(now)
    begin_mutation(conn)
    try:
        _require_active_project(conn, request.project_id)
        if request.item:
            from yoke_core.domain.session_launch_assignment import lock_assigned_item

            lock_assigned_item(
                conn, public_ref=request.item, project_id=request.project_id
            )
        request = default_launch_level(conn, request)
        request = managed_presentation.normalize_launch_presentation(request)
        request = validate_launch_request(request, max_body_bytes=max_body_bytes)
        requested = request
        existing = get_launch_by_dedupe(conn, auth.actor_id, request.idempotency_key)
        if request.level:
            request, preview = preview_level_launch(
                conn, auth=auth, request=request, now=current, eligibility=eligibility
            )
            if preview.launchable:
                request = validate_launch_request(
                    request, max_body_bytes=max_body_bytes
                )
        else:
            preview = preview_launch(
                conn,
                auth=auth,
                project_id=request.project_id,
                surface=request.executor_surface,
                machine_id=request.machine_id,
                allow_surface_fallback=request.allow_surface_fallback,
                surface_fallback_enabled=surface_fallback_enabled,
                now=current,
                model=request.model,
                eligibility=eligibility,
            )
        if existing is not None:
            outcome = deduplicated_outcome(
                conn,
                existing=existing,
                request=requested,
                preview=preview,
            )
            conn.commit()
            return outcome
        preview = admit_assigned_launch(
            conn, request=request, auth=auth, preview=preview, now=current
        )
        if not preview.launchable:
            from yoke_core.domain.session_surface_policy import launch_refusal_message

            raise SessionLaunchError(
                preview.outcome,
                str(preview.placement_reason)
                if preview.outcome == LEVEL_NO_CAPACITY
                else launch_refusal_message(conn, preview),
            )
        item_level = pin_item_level(conn, request=request, auth=auth)
        validate_model_selection(
            str(preview.selected_surface),
            model=request.model,
            reasoning_effort=request.reasoning_effort,
            context_window_tokens=request.context_window_tokens,
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
            sender_surface=request.sender_surface,
            project_id=request.project_id,
            body=request.instructions,
            created_at=current,
            expires_at=deadline_at,
        )
        inserted = insert_launch_request(
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
                conn, auth.actor_id, request.idempotency_key
            )
            if existing is None:
                raise SessionLaunchError("create_conflict", "launch insert conflicted")
            outcome = deduplicated_outcome(
                conn,
                existing=existing,
                request=requested,
                preview=preview,
            )
            conn.commit()
            return outcome
        launch = get_launch(conn, launch_id)
        conn.commit()
        return LaunchCreateOutcome(launch, preview, False, item_level)
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
    now: datetime | str | None = None,
    eligibility: LaunchEligibilityPort = derive_launch_eligibility,
) -> LaunchRecord:
    ensure_operator(auth)
    if not 60 <= deadline_seconds <= MAX_LAUNCH_DEADLINE_SECONDS:
        raise SessionLaunchError("deadline_invalid", "retry deadline is out of bounds")
    current = utc_now() if now is None else parse_instant(now)
    begin_mutation(conn)
    try:
        launch = get_launch(conn, launch_id, for_update=True)
        _require_active_project(conn, launch.project_id)
        pending = native_progress.retain_pending_native(conn, launch, now=current)
        if pending:
            conn.commit()
            return pending
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
        ask = retry_request(launch, conn=conn)
        if ask.level:
            ask, preview = preview_level_launch(
                conn, auth=auth, request=ask, now=current, eligibility=eligibility
            )
        else:
            preview = preview_launch(
                conn,
                auth=auth,
                project_id=launch.project_id,
                surface=launch.requested_surface,
                machine_id=launch.requested_machine_id,
                allow_surface_fallback=launch.allow_surface_fallback,
                surface_fallback_enabled=surface_fallback_enabled,
                now=current,
                model=launch.requested_model,
                eligibility=eligibility,
            )
        if ask.capacity_predecessor_session_id:
            preview = admit_assigned_launch(
                conn, request=ask, auth=auth, preview=preview, now=current
            )
        if not preview.launchable:
            raise SessionLaunchError(
                preview.outcome,
                str(preview.placement_reason)
                if preview.outcome == LEVEL_NO_CAPACITY
                else "no relay is eligible for retry",
            )
        validate_model_selection(
            str(preview.selected_surface),
            model=ask.model,
            reasoning_effort=ask.reasoning_effort,
            context_window_tokens=ask.context_window_tokens,
        )
        relay = preview.selected_relay
        assert relay is not None
        resolved = resolve_work_launch_selection(conn, request=ask, relay=relay)
        result = update_launch(
            conn,
            launch_id,
            state="assigned",
            selected_surface=relay.surface,
            resolved_model=resolved.model,
            resolved_reasoning_effort=resolved.reasoning_effort,
            resolved_context_window_tokens=resolved.context_window_tokens,
            assigned_relay_id=relay.relay_id,
            assigned_machine_id=relay.machine_id,
            placement_reason=preview.placement_reason,
            level_placement=stored_level_placement(
                preview, work_required=bool(ask.level or ask.work_required)
            ),
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
            **native_progress.cleared_native_launch_updates(),
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


__all__ = ["create_launch", "preview_launch", "retry_launch"]
