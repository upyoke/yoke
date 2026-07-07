"""Machine-config diagnostic function handlers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel

from yoke_core.domain import machine_config_status
from yoke_contracts.machine_config import schema as machine_config_contract
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)


class ConfigExampleRequest(BaseModel):
    pass


class ConfigExampleResponse(BaseModel):
    payload: Dict[str, Any]
    text: str


class StatusRequest(BaseModel):
    config_path: Optional[str] = None
    repo_root: Optional[str] = None
    explicit_env: Optional[str] = None
    check_reachability: bool = True


class StatusResponse(BaseModel):
    report: Dict[str, Any]


def handle_config_example(request: FunctionCallRequest) -> HandlerOutcome:
    del request
    return HandlerOutcome(
        result_payload={
            "payload": machine_config_contract.canonical_example_payload(),
            "text": machine_config_contract.canonical_example_text(),
        },
        primary_success=True,
    )


def handle_status(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    report = machine_config_status.build_status(
        config_path=payload.get("config_path"),
        repo_root=payload.get("repo_root"),
        explicit_env=payload.get("explicit_env"),
        check_reachability=bool(payload.get("check_reachability", True)),
    )
    return HandlerOutcome(result_payload={"report": report},
                          primary_success=bool(report.get("ok")))


__all__ = [
    "ConfigExampleRequest",
    "ConfigExampleResponse",
    "StatusRequest",
    "StatusResponse",
    "handle_config_example",
    "handle_status",
]
