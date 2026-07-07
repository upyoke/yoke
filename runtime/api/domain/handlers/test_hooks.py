from __future__ import annotations

from unittest.mock import patch

from yoke_core.domain.handlers.hooks import handle_hook_evaluate
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="hook.evaluate.run",
        actor=ActorContext(session_id="sess-1"),
        target=TargetRef(kind="global"),
        intent="test",
        payload=payload,
    )


def test_hook_evaluate_handler_delegates_to_hook_runner() -> None:
    with patch(
        "runtime.harness.hook_runner.__main__.main",
        return_value=0,
    ) as hook_main:
        outcome = handle_hook_evaluate(_request({"event_name": "PreToolUse"}))

    assert outcome.primary_success is True
    assert outcome.result_payload == {"exit_code": 0}
    hook_main.assert_called_once_with(["PreToolUse"])


def test_hook_evaluate_handler_delegates_dry_run_flag() -> None:
    with patch(
        "runtime.harness.hook_runner.__main__.main",
        return_value=0,
    ) as hook_main:
        outcome = handle_hook_evaluate(
            _request({"event_name": "Stop", "dry_run": True})
        )

    assert outcome.primary_success is True
    hook_main.assert_called_once_with(["Stop", "--dry-run"])


def test_hook_evaluate_handler_requires_event_name() -> None:
    outcome = handle_hook_evaluate(_request({}))

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"
