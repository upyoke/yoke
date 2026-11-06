# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from runtime.api.fixtures.session_holdings import insert_session

from yoke_core.domain.function_target_resolution import resolve_project_context

from yoke_core.domain.handlers.qa_catalog_reads import (
    handle_method_get,
    handle_method_list,
)

from yoke_core.domain.yoke_function_registry import RegistryEntry


def _request(function: str, payload: dict, session_id: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id=session_id),
        target=TargetRef(kind="global"),
        payload=payload,
    )
