# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import base64

import json

from pathlib import Path

from unittest import mock

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.pg_testdb import test_database

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain import qa_case_execution

from yoke_core.domain.browser_qa_results import RunResult, ScenarioResult

from yoke_core.domain.handlers import qa_case_execution as case_handlers

from yoke_core.domain.qa_case_execution_context import (
    get_case_execution_context,
)

from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)

from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases


def _case(method_id: str, runner_id: str, config: dict) -> dict:
    return {
        "requirement_id": 41,
        "public_ref": "YOK-9",
        "plan_id": 5,
        "case_key": "registered",
        "method_id": method_id,
        "runner_id": runner_id,
        "method_config": config,
        "project_id": 1,
        "project": "yoke",
        "lane_branch": None,
    }
