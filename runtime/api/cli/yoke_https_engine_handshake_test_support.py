# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io

import json

import urllib.error

from yoke_cli.transport import control_plane_payload

from yoke_cli.transport import https as yoke_transport

from yoke_cli.transport import https_engine_handshake as yoke_handshake

from yoke_cli.transport.dispatcher import emit_response

from yoke_cli.transport.https import HttpsConnection, relay_https

from yoke_cli.transport.https_engine_handshake import ServerHandshake

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)


def _request() -> FunctionCallRequest:
    return FunctionCallRequest(
        function="events.query.run",
        actor=ActorContext(session_id="s1"),
        target=TargetRef(kind="global"),
        request_id="req-1",
        payload={"limit": 1},
    )


def _ok_envelope() -> bytes:
    return json.dumps(
        {
            "success": True,
            "function": "events.query.run",
            "version": "v1",
            "request_id": "req-1",
            "result": {"events": []},
        }
    ).encode()


class _FakeResponse:
    def __init__(self, body: bytes, headers: dict | None = None):
        self._body = body
        self.headers = dict(headers or {})

    def read(self, *_args, **_kwargs) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False
