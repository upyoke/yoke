# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from unittest import mock

from types import SimpleNamespace

import pytest

from runtime.api.domain.qa_plan_execution_test_support import (
    TEST_EXECUTION_TARGET,
    TEST_ITEM_ID,
    TEST_ITEM_REF,
)

from yoke_contracts.api.function_call import ActorContext

from yoke_core.domain import qa_case_execution, qa_plan_execution

ACTOR = ActorContext(actor_id="7", session_id="ordered-failure")

CASE = {
    "requirement_id": 11,
    "item_id": TEST_ITEM_ID,
    "plan_id": 3,
    "case_key": "command",
    "case_position": 1,
    "baseline_position": 1,
    "host_baseline": None,
    "runner_id": "worktree_run",
}


def _begin_result() -> dict:
    return {
        "execution_id": "execution-1",
        "item_id": 42,
        "transition_id": "implemented",
        "state": "active",
        "roster_digest": "digest",
        "cursor_ordinal": 0,
        "execution_target": TEST_EXECUTION_TARGET,
        "execution_target_digest": "target-digest",
        "requirements": [CASE],
        "results": [],
    }
