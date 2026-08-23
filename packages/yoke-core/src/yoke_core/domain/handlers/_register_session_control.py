"""Registered session messaging, launch, and relay function family."""

from __future__ import annotations

from yoke_contracts.session_control import models as _models
from yoke_core.domain.handlers import session_launch as _launch
from yoke_core.domain.handlers import session_messages as _messages
from yoke_core.domain.handlers import session_messages_receipts as _receipts
from yoke_core.domain.handlers import session_relay as _relay


def _register(
    registry,
    function_id,
    handler,
    request_model,
    response_model,
    *,
    side_effects,
    owner_module,
    adapter_status="live",
) -> None:
    registry.register(
        function_id,
        handler,
        request_model,
        response_model,
        stability="stable",
        owner_module=owner_module,
        target_kinds=["global"],
        side_effects=side_effects,
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["verified_actor", "handler_enforced_project_authority"],
        adapter_status=adapter_status,
        claim_required_kind=None,
        ambient_session_required=False,
    )


def register(registry) -> None:
    message_specs = (
        (
            "preview",
            _messages.handle_message_preview,
            _models.MessagePreviewRequest,
            _models.MessagePreviewResponse,
            [],
        ),
        (
            "send",
            _messages.handle_message_send,
            _models.MessageSendRequest,
            _models.MessageSendResponse,
            ["session_messages_insert", "session_message_recipients_insert"],
        ),
        (
            "list",
            _messages.handle_message_list,
            _models.MessageListRequest,
            _models.MessageListResponse,
            [],
        ),
        (
            "get",
            _messages.handle_message_get,
            _models.MessageGetRequest,
            _models.MessageGetResponse,
            [],
        ),
        (
            "acknowledge",
            _receipts.handle_message_acknowledge,
            _models.MessageAcknowledgeRequest,
            _models.MessageMutationResponse,
            ["session_message_recipients_update"],
        ),
        (
            "cancel",
            _receipts.handle_message_cancel,
            _models.MessageCancelRequest,
            _models.MessageMutationResponse,
            ["session_messages_update", "session_message_recipients_update"],
        ),
        (
            "lease",
            _receipts.handle_message_lease,
            _models.MessageLeaseRequest,
            _models.MessageLeaseResponse,
            ["session_message_recipients_update", "session_message_attempts_insert"],
        ),
    )
    for operation, handler, request_model, response_model, effects in message_specs:
        _register(
            registry,
            f"session_control.message.{operation}",
            handler,
            request_model,
            response_model,
            side_effects=effects,
            owner_module=handler.__module__,
            adapter_status="internal" if operation == "lease" else "live",
        )

    launch_specs = (
        (
            "preview",
            _launch.handle_launch_preview,
            _models.LaunchPreviewRequest,
            _models.LaunchPreviewResponse,
            [],
        ),
        (
            "create",
            _launch.handle_launch_create,
            _models.LaunchCreateRequest,
            _models.LaunchResponse,
            ["session_messages_insert", "session_launches_insert"],
        ),
        (
            "get",
            _launch.handle_launch_get,
            _models.LaunchMutationRequest,
            _models.LaunchResponse,
            [],
        ),
        (
            "list",
            _launch.handle_launch_list,
            _models.LaunchListRequest,
            _models.LaunchListResponse,
            [],
        ),
        (
            "cancel",
            _launch.handle_launch_cancel,
            _models.LaunchMutationRequest,
            _models.LaunchResponse,
            ["session_launches_update"],
        ),
        (
            "retry",
            _launch.handle_launch_retry,
            _models.LaunchMutationRequest,
            _models.LaunchResponse,
            ["session_launches_update"],
        ),
        (
            "reconcile",
            _launch.handle_launch_reconcile,
            _models.LaunchReconcileRequest,
            _models.LaunchResponse,
            ["session_launches_update"],
        ),
    )
    for operation, handler, request_model, response_model, effects in launch_specs:
        _register(
            registry,
            f"session_control.launch.{operation}",
            handler,
            request_model,
            response_model,
            side_effects=effects,
            owner_module=handler.__module__,
        )

    _register(
        registry,
        "session_control.relay.list",
        _relay.handle_relay_list,
        _models.RelayListRequest,
        _models.RelayListResponse,
        side_effects=[],
        owner_module=_relay.__name__,
        adapter_status="internal",
    )
    _register(
        registry,
        "session_control.relay.claim",
        _relay.handle_relay_claim,
        _models.RelayClaimRequest,
        _models.RelayClaimResponse,
        side_effects=["session_relays_upsert", "session_control_jobs_lease"],
        owner_module=_relay.__name__,
        adapter_status="internal",
    )
    _register(
        registry,
        "session_control.relay.report",
        _relay.handle_relay_report,
        _models.RelayReportRequest,
        _models.RelayReportResponse,
        side_effects=["session_control_attempts_update", "session_relays_update"],
        owner_module=_relay.__name__,
        adapter_status="internal",
    )


__all__ = ["register"]
