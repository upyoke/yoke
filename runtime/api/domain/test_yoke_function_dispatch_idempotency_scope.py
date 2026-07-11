"""Scoped idempotency-key collision decisions."""

from __future__ import annotations

from unittest.mock import patch

from pydantic import BaseModel
import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    HandlerOutcome,
    TargetRef,
)
from yoke_core.domain import yoke_function_dispatch_idempotency as subject
from yoke_core.domain.yoke_function_idempotency_scope import (
    idempotency_payload_checksum,
)
from yoke_core.domain.yoke_function_registry import (
    lookup,
    register,
    reset_registry_for_tests,
)
from yoke_core.domain.handlers.__init_register__ import register_all_handlers


@pytest.fixture(autouse=True)
def _restore_production_registry():
    """Do not leak this module's intentionally tiny registry to later tests."""
    yield
    reset_registry_for_tests()
    register_all_handlers()


class _Shape(BaseModel):
    pass


def _entry():
    reset_registry_for_tests()
    register(
        "scoped.replay.test",
        lambda _request: HandlerOutcome(),
        _Shape,
        _Shape,
        stability="stable",
        owner_module="test",
        target_kinds=["global"],
        side_effects=["mutation"],
        emitted_event_names=[],
        guardrails=[],
        adapter_status="live",
    )
    return lookup("scoped.replay.test")


def _request(
    *, actor: str = "actor-1", payload=None, target: TargetRef | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="scoped.replay.test",
        actor=ActorContext(actor_id=actor, session_id="session-1"),
        target=target or TargetRef(kind="global"),
        request_id="same-key",
        payload=dict(payload or {}),
    )


def _decide(request, stored, *, scope="project:1"):
    with patch.object(subject, "_idempotency_lookup", return_value=stored):
        return subject.handle_idempotency(
            _entry(),
            request,
            identity_context=None,
            permission_key="items.write",
            project="one",
            authorization_scope=scope,
            payload_checksum=idempotency_payload_checksum(request),
        )


def _stored(*, actor="actor-1", scope="project:1", payload=None):
    return (
        {"ok": True},
        "scoped.replay.test",
        actor,
        scope,
        idempotency_payload_checksum(_request(payload=payload)),
    )


def test_same_function_different_authenticated_actor_collides() -> None:
    response = _decide(_request(actor="actor-2"), _stored())
    assert response.success is False
    assert response.error.code == "idempotency_key_collision"


def test_same_function_different_authorized_project_collides() -> None:
    response = _decide(_request(), _stored(scope="project:1"), scope="project:2")
    assert response.success is False
    assert response.error.code == "idempotency_key_collision"


def test_same_function_different_canonical_payload_collides() -> None:
    response = _decide(_request(payload={"value": "new"}), _stored(payload={"value": "old"}))
    assert response.success is False
    assert response.error.code == "idempotency_key_collision"


def test_same_function_different_target_collides() -> None:
    response = _decide(
        _request(target=TargetRef(kind="item", item_id=22)),
        _stored(),
    )
    assert response.success is False
    assert response.error.code == "idempotency_key_collision"
