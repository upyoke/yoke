# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_contracts.api.function_call import (
    FunctionCallResponse as FunctionCallResponse,
    FunctionError as FunctionError,
)

from yoke_core.domain import worktree_dirty_main_guard as guard

from yoke_core.domain import worktree_preflight_steps as steps


def _resp(function, *, result=None, success=True, error=None):
    return FunctionCallResponse(
        success=success,
        function=function,
        version="v1",
        result=result or {},
        error=error,
    )


def _patch_facade(monkeypatch, router):
    from yoke_core.api import service_client_structured_api_adapter as facade

    monkeypatch.setattr(facade, "call_dispatcher", router)
