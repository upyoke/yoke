# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import pytest

from runtime.api.auth_test_helpers import mint_api_auth_context

from runtime.api.conftest import insert_event

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.handlers import events_reads


def request(verb, actor, payload):
    return FunctionCallRequest(
        function=f"events.{verb}.run",
        actor=ActorContext(actor_id=str(actor), session_id="caller"),
        target=TargetRef(kind="global"),
        payload=payload,
    )
