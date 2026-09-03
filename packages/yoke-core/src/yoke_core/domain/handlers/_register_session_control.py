"""Registered session messaging, launch, and relay function family."""

from __future__ import annotations

from yoke_contracts.session_control import models as _models
from yoke_contracts.session_control.private_route_qualification import (
    PrivateRouteQualificationOpenRequest,
    PrivateRouteQualificationOpenResponse,
)
from yoke_contracts.session_control.termination import (
    SessionTerminateRequest,
    SessionTerminateResponse,
)
from yoke_contracts.session_control.evidence_fetch import (
    EvidenceGetRequest,
    EvidenceGetResponse,
)
from yoke_contracts.session_control.function_ids import EVIDENCE_GET_FUNCTION_ID
from yoke_contracts.session_control.wake import SessionWakeRequest, SessionWakeResponse
from yoke_core.domain.handlers import session_launch as _launch
from yoke_core.domain.handlers._register_session_messages import (
    register_message_functions,
)
from yoke_core.domain.handlers import session_evidence as _evidence
from yoke_core.domain.handlers import session_relay as _relay
from yoke_contracts.session_control import native_turn_end as _turn_end
from yoke_core.domain.session_native_turn_end import EVENT_SESSION_TURN_END_OBSERVED
from yoke_core.domain.handlers import session_termination as _termination
from yoke_core.domain.handlers import session_wake as _wake
from yoke_core.domain.handlers import session_qualification as _qualification
from yoke_core.domain.handlers import session_surface_policy as _surface_policy
from yoke_contracts.session_control.surface_policy import (
    SurfacePolicyClearRequest,
    SurfacePolicyListRequest,
    SurfacePolicyListResponse,
    SurfacePolicyMutationResponse,
    SurfacePolicySetRequest,
)
from yoke_core.domain.session_termination_events import EVENT_SESSION_TERMINATED
from yoke_core.domain.sessions_analytics import EVENT_HARNESS_SESSION_ENDED


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
    guardrails=None,
    claim_required_kind=None,
    emitted_event_names=None,
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
        emitted_event_names=emitted_event_names or ["YokeFunctionCalled"],
        guardrails=guardrails
        or ["verified_actor", "handler_enforced_project_authority"],
        adapter_status=adapter_status,
        claim_required_kind=claim_required_kind,
        ambient_session_required=False,
    )


def register(registry) -> None:
    _register(
        registry,
        "session_control.session.terminate",
        _termination.handle_session_terminate,
        SessionTerminateRequest,
        SessionTerminateResponse,
        side_effects=[
            "harness_sessions_update",
            "work_claims_update",
            "session_message_recipients_update",
            "session_termination_reaps_upsert",
        ],
        owner_module=_termination.__name__,
        guardrails=[
            "verified_actor",
            "handler_enforced_operator_or_steering_authority",
        ],
        emitted_event_names=["YokeFunctionCalled", EVENT_SESSION_TERMINATED],
    )
    _register(
        registry,
        "session_control.session.wake",
        _wake.handle_session_wake,
        SessionWakeRequest,
        SessionWakeResponse,
        side_effects=[
            "session_messages_insert",
            "session_message_recipients_insert",
        ],
        owner_module=_wake.__name__,
        guardrails=[
            "verified_actor",
            "handler_enforced_project_authority",
        ],
    )
    _register(
        registry,
        "session_control.qualification.open",
        _qualification.handle_qualification_open,
        PrivateRouteQualificationOpenRequest,
        PrivateRouteQualificationOpenResponse,
        side_effects=["work_claims_insert"],
        owner_module=_qualification.__name__,
        guardrails=[
            "operator_override_required",
            "handler_enforced_project_authority",
            "stage_only_exact_release",
        ],
        claim_required_kind="operator_override",
    )
    register_message_functions(registry, _register)

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
        side_effects=[
            "session_relays_upsert",
            "session_control_jobs_lease",
            "work_claims_update_released_at",
        ],
        owner_module=_relay.__name__,
        adapter_status="internal",
    )
    _register(
        registry,
        "session_control.relay.liveness",
        _relay.handle_relay_liveness,
        _models.RelayLivenessRequest,
        _models.RelayLivenessResponse,
        side_effects=[
            "harness_sessions_update",
            "work_claims_update_released_at",
        ],
        owner_module=_relay.__name__,
        adapter_status="internal",
        emitted_event_names=["YokeFunctionCalled", EVENT_HARNESS_SESSION_ENDED],
    )
    _register(
        registry,
        "session_control.relay.turn_end",
        _relay.handle_relay_turn_end,
        _turn_end.RelayTurnEndRequest,
        _turn_end.RelayTurnEndResponse,
        side_effects=["harness_sessions_update"],
        owner_module=_relay.__name__,
        adapter_status="internal",
        emitted_event_names=["YokeFunctionCalled", EVENT_SESSION_TURN_END_OBSERVED],
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

    _register(
        registry,
        EVIDENCE_GET_FUNCTION_ID,
        _evidence.handle_evidence_get,
        EvidenceGetRequest,
        EvidenceGetResponse,
        side_effects=["session_evidence_fetches_upsert"],
        owner_module=_evidence.__name__,
    )

    policy_specs = (
        (
            "disable",
            _surface_policy.handle_surface_policy_set,
            SurfacePolicySetRequest,
            SurfacePolicyMutationResponse,
            ["session_surface_policies_insert"],
        ),
        (
            "enable",
            _surface_policy.handle_surface_policy_clear,
            SurfacePolicyClearRequest,
            SurfacePolicyMutationResponse,
            ["session_surface_policies_update"],
        ),
        (
            "list",
            _surface_policy.handle_surface_policy_list,
            SurfacePolicyListRequest,
            SurfacePolicyListResponse,
            [],
        ),
    )
    for operation, handler, request_model, response_model, effects in policy_specs:
        _register(
            registry,
            f"session_control.surface_policy.{operation}",
            handler,
            request_model,
            response_model,
            side_effects=effects,
            owner_module=handler.__module__,
            guardrails=[
                "verified_actor",
                "handler_enforced_operator_or_steering_authority",
            ]
            if operation != "list"
            else ["verified_actor"],
        )


__all__ = ["register"]
