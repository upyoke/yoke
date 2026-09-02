"""Self-contained registrations for Inbox and decision actions."""

from __future__ import annotations

from yoke_core.domain.handlers import decision_request_disposition as _disposition
from yoke_core.domain.handlers import inbox_decisions as _inbox
from yoke_core.domain.handlers import inbox_decision_models as _models
from yoke_core.domain import machine_approval_requests as _machine


def _register(
    registry,
    function_id,
    handler,
    request_model,
    response_model,
    *,
    side_effects,
    events,
    guardrails,
    owner_module="yoke_core.domain.handlers.inbox_decisions",
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
        emitted_event_names=["YokeFunctionCalled", *events],
        guardrails=guardrails,
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )


def register(registry) -> None:
    _register(
        registry,
        "inbox.list",
        _inbox.handle_inbox_list,
        _inbox.InboxListRequest,
        _inbox.InboxListResponse,
        side_effects=[],
        events=[],
        guardrails=["actor_required", "authority_union"],
    )
    _register(
        registry,
        "machine_approval.lifecycle.apply",
        _machine.apply_machine_approval_lifecycle_request,
        _models.MachineApprovalLifecycleRequest,
        _models.MachineApprovalLifecycleResponse,
        side_effects=[
            "decision_requests_insert",
            "decision_requests_resolve",
            "decision_requests_withdraw",
        ],
        events=[
            "DecisionRequestCreated",
            "DecisionRequestResolved",
            "DecisionRequestWithdrawn",
        ],
        guardrails=[
            "actor_required",
            "org_scope_exact",
            "tenant_identity_org",
            "closed_lifecycle_state",
            "terminal_replay_idempotent",
        ],
        owner_module="yoke_core.domain.machine_approval_requests",
    )
    _register(
        registry,
        "decision_requests.create",
        _inbox.handle_decision_create,
        _inbox.DecisionCreateRequest,
        _inbox.DecisionMutationResponse,
        side_effects=["decision_requests_insert"],
        events=["DecisionRequestCreated"],
        guardrails=["closed_kind", "typed_subject", "authority_union"],
    )
    _register(
        registry,
        "decision_requests.resolve",
        _inbox.handle_decision_resolve,
        _inbox.DecisionResolveRequest,
        _inbox.DecisionMutationResponse,
        side_effects=["decision_requests_resolve"],
        events=["DecisionRequestResolved"],
        guardrails=["actor_required", "live_authority_union", "closed_action"],
    )
    _register(
        registry,
        "decision_requests.withdraw",
        _inbox.handle_decision_withdraw,
        _inbox.DecisionWithdrawRequest,
        _inbox.DecisionMutationResponse,
        side_effects=["decision_requests_withdraw"],
        events=["DecisionRequestWithdrawn"],
        guardrails=[
            "actor_required",
            "live_authority_union",
            "subject_ended",
            "never_silent_expiry",
        ],
    )
    _register(
        registry,
        "decision_requests.dispose_ended",
        _disposition.handle_decision_dispose_ended,
        _models.DecisionDisposeEndedRequest,
        _models.DecisionDisposeEndedResponse,
        side_effects=[
            "qa_plan_executions_update",
            "decision_requests_withdraw",
        ],
        events=["DecisionRequestWithdrawn"],
        guardrails=["subject_ended", "never_silent_expiry"],
        owner_module="yoke_core.domain.handlers.decision_request_disposition",
    )


__all__ = ["register"]
