# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from runtime.api.deployment_stage_approval_fixture import (
    OpenConnection,
    seed_gate_run,
)

from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)

from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
)

from yoke_core.domain.deployment_approval_requests import (
    evaluate_deployment_stage_approval,
)


def _evaluate_request(run_id: str, stage: str, *, actor_id=None):
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )
    from yoke_core.domain.deployment_approval_requests import (
        EVALUATE_STAGE_APPROVAL_FUNCTION,
    )

    return FunctionCallRequest(
        function=EVALUATE_STAGE_APPROVAL_FUNCTION,
        actor=ActorContext(actor_id=actor_id, session_id="gate-session"),
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload={"stage": stage},
    )


def _evaluate(test_db, monkeypatch, run_id, stage, *, actor_id=None):
    """Drive the registered operation the way the serving build runs it."""
    import yoke_core.domain.db_helpers as db_helpers
    from yoke_core.domain.handlers import deployment_stage_approval

    monkeypatch.setattr(
        db_helpers,
        "connect",
        lambda: OpenConnection(test_db),
    )
    return deployment_stage_approval.handle_deployment_stage_approval_evaluate(
        _evaluate_request(run_id, stage, actor_id=actor_id)
    )
