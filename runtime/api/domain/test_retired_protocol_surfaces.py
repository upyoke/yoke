"""Removed protocol names refuse with a named client floor, never execute."""

from importlib import import_module
from unittest.mock import patch

from yoke_core.domain import events
from yoke_core.domain.retired_protocol_surfaces import retired_surface_reason, unregistered_function_error


def test_every_recorded_retirement_names_its_floor():
    history = import_module("yoke_core.domain.migrations.0095_feedback_categories")
    names = {"function": [family + "." + operation for family, operations in history.RETIRED_FUNCTION_FAMILIES.items() for operation in operations],
             "hook": history.RETIRED_HOOKS, "event": history.RETIRED_EVENTS}
    with patch("yoke_core.domain.retired_protocol_surfaces.retirement_floor", return_value="0.2.0.202610290013"):
        for kind, retired in names.items():
            for name in retired:
                reason = retired_surface_reason(kind, name)
                assert "floor 0.2.0.202610290013" in reason
                if kind == "function":
                    assert unregistered_function_error(name)[0] == "function_version_skew"
                if kind == "event":
                    result = events.emit_event(name, event_kind="system", event_type="fixture")
                    assert not result.ok
                    assert result.reason == reason
    assert retired_surface_reason("function", "current.example") is None


def test_removed_function_refuses_through_dispatch(test_db):
    from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
    from yoke_core.domain.yoke_function_dispatch import _dispatch_impl
    history = import_module("yoke_core.domain.migrations.0095_feedback_categories")
    family, operations = next(iter(history.RETIRED_FUNCTION_FAMILIES.items()))
    request = FunctionCallRequest(function=family + "." + operations[0],
        actor=ActorContext(session_id="fixture"), target=TargetRef(kind="global"), payload={})
    with patch("yoke_core.domain.retired_protocol_surfaces.retirement_floor", return_value="0.2.0.202610290013"):
        response = _dispatch_impl(request)
    assert not response.success
    assert response.error.code == "function_version_skew"
    assert "floor 0.2.0.202610290013" in response.error.message


def test_removed_hook_entrypoint_refuses_before_evaluation():
    from fastapi import BackgroundTasks
    from yoke_core.api.routes.hooks import post_hooks_evaluate
    from yoke_core.api.routes.hooks_wire_contract import HookEvaluateRequest
    history = import_module("yoke_core.domain.migrations.0095_feedback_categories")
    request = HookEvaluateRequest(event_name="PostToolUse", entrypoint=history.RETIRED_HOOKS[0])
    with patch("yoke_core.domain.retired_protocol_surfaces.retirement_floor", return_value="0.2.0.202610290013"):
        response = post_hooks_evaluate(None, request, BackgroundTasks())
    assert response.status_code == 400
    assert b"floor 0.2.0.202610290013" in response.body
