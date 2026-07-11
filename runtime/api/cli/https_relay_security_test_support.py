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
NESTED_PASSWORD = "nested-password-must-not-escape"
CAPABILITY_SECRET = "capability-secret-must-not-escape"
TRANSPORT_TOKEN = "relay-bearer-must-not-escape"
CONNECTION = HttpsConnection(
    api_url="https://api.example",
    token=TRANSPORT_TOKEN,
)


def sensitive_request() -> FunctionCallRequest:
    return FunctionCallRequest(
        function="projects.github_binding.bind",
        actor=ActorContext(session_id="sensitive-relay-test"),
        target=TargetRef(kind="global"),
        request_id="sensitive-relay-request",
        payload={
            "github_user_access_token": USER_TOKEN,
            "nested": {
                "credentials": {"password": NESTED_PASSWORD},
            },
            "capability": {
                "key": "secret_access_key",
                "value": CAPABILITY_SECRET,
            },
        },
    )


def envelope(
    *,
    success: bool = True,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> bytes:
    return json.dumps(
        {
            "success": success,
            "function": "projects.github_binding.bind",
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
    "CAPABILITY_SECRET",
    "CONNECTION",
    "FakeResponse",
    "NESTED_PASSWORD",
    "NoReadResponse",
    "TRANSPORT_TOKEN",
    "USER_TOKEN",
    "envelope",
    "sensitive_request",
    "serialized_response",
]
