"""Registered terminalization handler validation and result mapping."""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.deployment_run_terminalization import RunTerminalization
from yoke_core.domain.handlers.deployment_run_terminalization import (
    handle_deployment_run_terminalize,
)


def _request(payload, actor_id="1"):
    return deployment_request(
        function="deployment_runs.terminalize",
        target=TargetRef(
            kind="workflow_run", workflow_run_id="run-20260804-010",
        ),
        payload=payload,
        actor_id=actor_id,
    )


def test_handler_calls_the_guarded_domain_authority():
    result = RunTerminalization(
        run_id="run-20260804-010",
        project="yoke",
        prior_status="executing",
        final_status="cancelled",
        reason="No external job remains",
        terminalized_at="2026-08-05T12:00:00Z",
        terminalized_by_actor_id=None,
        terminalized_by_session_id="s-1",
        event_id="event-1",
    )
    with patch(
        "yoke_core.domain.deployment_run_terminalization.terminalize_run",
        return_value=result,
    ) as terminalize:
        outcome = handle_deployment_run_terminalize(_request({
            "disposition": "cancelled",
            "reason": "No external job remains",
        }, actor_id="operator"))
    assert outcome.primary_success is True
    assert outcome.result_payload["event_id"] == "event-1"
    terminalize.assert_called_once_with(
        "run-20260804-010",
        disposition="cancelled",
        reason="No external job remains",
        actor_id=None,
        session_id="s-1",
    )


def test_handler_requires_reason():
    missing_reason = handle_deployment_run_terminalize(_request({
        "disposition": "failed", "reason": "  ",
    }))
    assert missing_reason.error.code == "payload_invalid"


def test_terminalization_function_is_registered_with_atomic_guardrails():
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.domain import yoke_function_registry as registry

    registry.reset_registry_for_tests()
    try:
        register_all_handlers()
        entry = registry.lookup("deployment_runs.terminalize")
        assert entry is not None
        assert entry.side_effects == ("deployment_runs_update", "events_insert")
        assert "atomic_audit_event" in entry.guardrails
        assert entry.target_kinds == ("workflow_run",)
        assert entry.ambient_session_required is False
    finally:
        registry.reset_registry_for_tests()
