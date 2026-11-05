# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import os

import sys

import time

import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.api_items_test_helpers import (
    _client_for_db,
    make_test_db_fixture,
)

pytestmark = pytest.mark.usefixtures("bound_project_context")


@pytest.fixture()
def hooks_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(hooks_db):
    with _client_for_db(hooks_db["db_path"]) as authed:
        yield authed


def _request_body(**overrides) -> dict:
    body = {
        "hook_schema": 1,
        "event_name": "PreToolUse",
        "project_id": 1,
        "stdin": json.dumps(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": "/client/repo/file.py"},
                "cwd": "/client/repo",
                "session_id": "remote-hook-session",
                "project_id": 1,
            }
        ),
        "executor": "claude",
        "agent_type": None,
        "deadline_ms": 2500,
    }
    body.update(overrides)
    return body
