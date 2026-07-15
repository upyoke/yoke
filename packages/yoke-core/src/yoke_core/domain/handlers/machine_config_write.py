"""Machine-config writer function handlers.

These mutate the MACHINE-LOCAL ``~/.yoke/config.json`` (or the
``config_path`` override) on whatever host dispatches them — meaningful
in-process, nonsensical to relay to a cloud env. The CLI-only
``--token-stdin`` flow is deliberately absent here: raw secret values
must never transit a function payload (telemetry records payloads);
the function surface accepts credential file REFERENCES only.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel

from yoke_core.domain import machine_config_writer
from yoke_core.domain.machine_config import MachineConfigError
from yoke_core.domain.machine_config_writer import MachineConfigWriteError
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class EnvUseRequest(BaseModel):
    env: str
    config_path: Optional[str] = None


class EnvUseResponse(BaseModel):
    active_env: str
    config: str


class ConnectionSetRequest(BaseModel):
    env: str
    transport: Optional[str] = None
    api_url: Optional[str] = None
    token_file: Optional[str] = None
    dsn_file: Optional[str] = None
    config_path: Optional[str] = None


class ConnectionSetResponse(BaseModel):
    env: str
    connection: Dict[str, Any]
    active_env: str
    config: str


class ConnectionRemoveRequest(BaseModel):
    env: str
    config_path: Optional[str] = None


class ConnectionRemoveResponse(BaseModel):
    removed_env: str
    credential_removed: bool
    project_mappings_removed: int
    config: str


class AuthSetRequest(BaseModel):
    env: str
    token_file: Optional[str] = None
    dsn_file: Optional[str] = None
    config_path: Optional[str] = None


class AuthSetResponse(BaseModel):
    env: str
    credential_source: Dict[str, Any]
    config: str


class ProjectRegisterRequest(BaseModel):
    repo_root: str
    project_id: int
    board_scope: Optional[str] = None
    board_render_path: Optional[str] = None
    config_path: Optional[str] = None


class ProjectRegisterResponse(BaseModel):
    checkout: str
    entry: Dict[str, Any]
    config: str


class StampProjectEnvRequest(BaseModel):
    env: Optional[str] = None
    config_path: Optional[str] = None


class StampProjectEnvResponse(BaseModel):
    env: str
    stamped: list
    skipped: list
    config: str


def handle_env_use(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    return _outcome(lambda: machine_config_writer.set_active_env(
        str(payload.get("env") or ""),
        path=payload.get("config_path"),
    ))


def handle_connection_set(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    return _outcome(lambda: machine_config_writer.set_connection(
        str(payload.get("env") or ""),
        transport=payload.get("transport"),
        api_url=payload.get("api_url"),
        token_file=payload.get("token_file"),
        dsn_file=payload.get("dsn_file"),
        path=payload.get("config_path"),
    ))


def handle_connection_remove(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    return _outcome(lambda: machine_config_writer.remove_connection(
        str(payload.get("env") or ""), path=payload.get("config_path"),
    ))


def handle_auth_set(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    return _outcome(lambda: machine_config_writer.set_credential(
        str(payload.get("env") or ""),
        token_file=payload.get("token_file"),
        dsn_file=payload.get("dsn_file"),
        path=payload.get("config_path"),
    ))


def handle_project_register(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    return _outcome(lambda: machine_config_writer.register_project(
        str(payload.get("repo_root") or ""),
        payload.get("project_id"),
        board_scope=payload.get("board_scope"),
        board_render_path=payload.get("board_render_path"),
        path=payload.get("config_path"),
    ))


def handle_stamp_project_env(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    return _outcome(lambda: machine_config_writer.stamp_untagged_project_envs(
        payload.get("env"),
        path=payload.get("config_path"),
    ))


def _outcome(operation) -> HandlerOutcome:
    try:
        result = operation()
    except (MachineConfigWriteError, MachineConfigError) as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="machine_config_write_refused",
                message=str(exc),
            ),
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "AuthSetRequest",
    "AuthSetResponse",
    "ConnectionSetRequest",
    "ConnectionSetResponse",
    "ConnectionRemoveRequest",
    "ConnectionRemoveResponse",
    "EnvUseRequest",
    "EnvUseResponse",
    "ProjectRegisterRequest",
    "ProjectRegisterResponse",
    "StampProjectEnvRequest",
    "StampProjectEnvResponse",
    "handle_auth_set",
    "handle_connection_set",
    "handle_connection_remove",
    "handle_env_use",
    "handle_project_register",
    "handle_stamp_project_env",
]
