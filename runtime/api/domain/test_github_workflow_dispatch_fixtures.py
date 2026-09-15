"""Shared fixtures for the GitHub workflow dispatch intent test suite.

Split out so ``test_github_workflow_dispatch.py`` (single-actor and
sequential cross-actor scenarios) and
``test_github_workflow_dispatch_concurrency.py`` (genuine concurrent races
and additional non-owner edge cases) share one request/payload/intent
builder instead of duplicating fixture code.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.github_workflow_dispatch_intents import claim_attempt
from yoke_core.domain.handlers.github_actions_workflow_dispatch import (
    WorkflowDispatchRequest,
)
from yoke_core.domain.yoke_function_idempotency_scope import (
    idempotency_payload_checksum,
)

REQUEST_ID = "workflow-dispatch:candidatesha:consumersha:example-consumer-check.yml"
INPUTS = {"product_ref": "candidatesha"}
REPO = "upyoke/example-consumer"
WORKFLOW = "example-consumer-check.yml"


def build_request(
    actor_id: str, *, request_id: str = REQUEST_ID
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="github_actions.workflow.dispatch",
        actor=ActorContext(actor_id=actor_id, session_id=f"session-{actor_id}"),
        target=TargetRef(kind="global"),
        request_id=request_id,
        payload={
            "repo": REPO,
            "workflow": WORKFLOW,
            "ref": "main",
            "inputs": INPUTS,
            "project": "example-consumer",
            "correlation_input": "yoke_dispatch_id",
        },
        options={"authorized_project_id": 3},
    )


def build_payload() -> WorkflowDispatchRequest:
    return WorkflowDispatchRequest(
        repo=REPO,
        workflow=WORKFLOW,
        ref="main",
        inputs=INPUTS,
        project="example-consumer",
        correlation_input="yoke_dispatch_id",
    )


def seed_intent(
    *,
    owner_actor: str,
    correlation_id: str = "corr-1",
    request_id: str = REQUEST_ID,
) -> None:
    checksum = idempotency_payload_checksum(
        build_request(owner_actor, request_id=request_id)
    )
    claimed = claim_attempt(
        request_id=request_id,
        attempt=1,
        actor_id=owner_actor,
        authorization_scope="project:3",
        payload_checksum=checksum,
        repo=REPO,
        workflow=WORKFLOW,
        workflow_ref="main",
        inputs=INPUTS,
        correlation_id=correlation_id,
    )
    assert claimed


def refusing_rest_post(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("a non-owning reuse caller must never POST a dispatch")
