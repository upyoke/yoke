# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Optional

from unittest import mock

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    HandlerOutcome,
    TargetRef,
)

from yoke_core.domain import session_less_actor_binding as binding

from yoke_core.domain import yoke_function_actor_identity as identity

from yoke_core.domain.yoke_function_registry import RegistryEntry


class _Model(BaseModel):
    pass


def _entry(
    *,
    side_effects=("write",),
    ambient_session_required: bool = False,
    function_id: str = "project_structure.patch.apply",
) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=lambda request: HandlerOutcome(result_payload={}, primary_success=True),
        request_model=_Model,
        response_model=_Model,
        stability="stable",
        owner_module="test",
        target_kinds=("project_structure",),
        side_effects=tuple(side_effects),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
        ambient_session_required=ambient_session_required,
    )


def _request(actor_id: Optional[str] = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="project_structure.patch.apply",
        actor=ActorContext(actor_id=actor_id, session_id=""),
        target=TargetRef(kind="global"),
    )
