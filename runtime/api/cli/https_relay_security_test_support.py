"""Shared fixtures for hostile HTTPS function-relay response tests."""

from __future__ import annotations

import io
import json
from typing import Any

from yoke_cli.transport.https import HttpsConnection
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


USER_TOKEN = "ghu-user-token-must-not-escape"
TRANSPORT_TOKEN = "relay-bearer-must-not-escape"
CONNECTION = HttpsConnection(
    api_url="https://api.example",
    token=TRANSPORT_TOKEN,
)


def sensitive_request() -> FunctionCallRequest:
    return FunctionCallRequest(
        function="projects.capability_secret.set",
        actor=ActorContext(session_id="sensitive-relay-test"),
        target=TargetRef(kind="global"),
        request_id="sensitive-relay-request",
        payload={
            "project": "example",
            "cap_type": "database",
            "key": "DATABASE_URL",
            "value": USER_TOKEN,
        },
    )


def declared_secret_request(
    function: str, field: str, value: str
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id="actions-secret-relay-test"),
        target=TargetRef(kind="global"),
        request_id="actions-secret-relay-request",
        payload={
            "repo": "example/project",
            "name": "DATABASE_URL",
            field: value,
            "project": "example",
        },
    )


def envelope(
    *,
    function: str = "projects.github_binding.bind",
    success: bool = True,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> bytes:
    return json.dumps(
        {
            "success": success,
            "function": function,
            "version": "v1",
            "request_id": "sensitive-relay-request",
            "result": result or {},
            "error": error,
            "warnings": warnings or [],
        }
    ).encode("utf-8")


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, headers: dict[str, str] | None = None):
        super().__init__(body)
        self.headers = dict(headers or {})
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class NoReadResponse(FakeResponse):
    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        raise AssertionError("Content-Length preflight must reject before read")


def serialized_response(response: Any) -> str:
    return response.model_dump_json()


__all__ = [
    "CONNECTION",
    "FakeResponse",
    "NoReadResponse",
    "TRANSPORT_TOKEN",
    "USER_TOKEN",
    "declared_secret_request",
    "envelope",
    "sensitive_request",
    "serialized_response",
]
