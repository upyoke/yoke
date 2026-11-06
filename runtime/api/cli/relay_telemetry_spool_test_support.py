# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from runtime.api.cli.https_relay_security_test_support import sensitive_request

from yoke_cli.transport import https_relay_outcome

from yoke_cli.transport import relay_telemetry

from yoke_contracts.api.function_call import FunctionCallResponse


def _emit_response(
    *, success: bool, code: str = relay_telemetry.TRANSPORT_FAILED_CODE
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=success,
        function="events.emit",
        version="v1",
        request_id="emit",
        result={"emitted": True} if success else {},
        error=None if success else {"code": code, "message": "no"},
    )


def _spooled() -> list[dict]:
    path = relay_telemetry.spool_path()
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _record_telemetry(
    *,
    transport_delivered: bool,
    application_succeeded: bool | None,
    function_id: str = "items.detail.get",
    project: str = "yoke",
) -> None:
    relay_telemetry.record(
        function_id=function_id,
        session_id="session-a",
        env="prod",
        attempts=3,
        transport_delivered=transport_delivered,
        application_succeeded=application_succeeded,
        failure_class=(
            ""
            if application_succeeded is True
            else "item_not_found"
            if transport_delivered
            else "https_transport_failed"
        ),
        project=project,
    )
