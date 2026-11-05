# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io

import json

import sys

import pytest

from runtime.api.cli.yoke_operations_cli_hooks_test_support import (
    _FakeResponse,
    cli_main,
    https_connection,
    local_subset,
)

from yoke_contracts.hook_runner.config_owner import (
    CURSOR_EXECUTOR_ID,
    EXECUTOR_ENV_VAR,
)

from yoke_harness.hooks.decision_render import (
    HOOK_SPECIFIC_OUTPUT_KEY,
    render_context_stdout,
)

from yoke_harness.hooks.local_subset import LocalSubsetEvaluation

ORIENTATION = "## Yoke Orientation\n\nsession s-1\n"


def _server_response(**overrides) -> bytes:
    payload = {
        "hook_schema": 1,
        "stdout": "",
        "exit_code": 0,
        "wait_ms": 1,
        "degraded": [],
        "outcome": "completed",
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


@pytest.fixture()
def oriented(monkeypatch):
    """Make the client-side orientation composer return fixed text."""
    monkeypatch.setattr(
        "yoke_core.domain.session_orientation.orientation_for_hook",
        lambda event_name, stdin_data, *, cursor=False: ORIENTATION,
    )
