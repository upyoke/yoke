# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.cli.yoke_https_engine_handshake_test_support import _request as _request

import http.client

import io

import json

import urllib.error

import pytest

from yoke_cli.transport import https as yoke_transport

from yoke_contracts import https_retry_policy as https_retry_policy

from yoke_cli.transport.https import (
    HttpsConnection,
    TransportError,
    relay_https,
    resolve_https_connection,
)

from yoke_contracts.machine_config.schema import (
    MachineConfigContractError,
)

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
