# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from dataclasses import replace

from pathlib import Path

import json

import sqlite3

from yoke_contracts.session_usage_facts import usage_from_document

from yoke_contracts.session_usage_sources import UNNAMED_MODEL

from yoke_harness.cursor_native_result_usage import (
    fold_launch_native_result,
    fold_native_result_usage,
    native_result_payload,
    session_usage_document,
)

from yoke_harness.session_relay_native_capture_format import (
    STATE_EXITED,
    STATE_RUNNING,
    compose_capture,
    parse_capture,
)

from runtime.harness.session_usage_test_support import (  # noqa: F401
    machine_home,
)

CONVERSATION = "fc6a9de6-66d6-4e8a-a740-3f83262475ac"

REQUEST = "77fbd870-80b3-4816-b4f9-f4a6150e9c3c"

NATIVE_RESULT_LINE = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 17137,
        "duration_api_ms": 17137,
        "result": "ok",
        "session_id": CONVERSATION,
        "request_id": REQUEST,
        "usage": {
            "inputTokens": 102596,
            "outputTokens": 30,
            "cacheReadTokens": 9600,
            "cacheWriteTokens": 0,
        },
    }
)
