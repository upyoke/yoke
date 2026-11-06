# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io

import json

import sys

from contextlib import redirect_stderr, redirect_stdout

from unittest.mock import patch

from uuid import UUID

import pytest

from runtime.api.cli.hook_relay_test_support import (
    local_subset as local_subset,
    https_connection as https_connection,
    _RESOLVE,
    _HOME_FACT,
)  # noqa: F401

from yoke_cli.commands.adapters import hooks as hooks_adapter

from yoke_cli.main import main as cli_main

from yoke_cli.transport.https import TransportError


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def geturl(self) -> str:
        return "https://env.example/v1/hooks/evaluate"

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args) -> bool:
        return False
