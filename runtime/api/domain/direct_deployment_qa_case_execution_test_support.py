# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.deployment_qa_stage_execution_test_support import _seed_run

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement

from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item

from yoke_core.domain.handlers import qa_requirement_create

from yoke_core.domain.qa_case_execution_context import get_case_execution_context

from yoke_core.domain.qa_requirement_config_update import apply_requirement_update

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _qa_stages() -> list[dict]:
    return [
        {
            "name": "deploy",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": "item-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "item",
            "target": {
                "kind": "persistent_environment",
                "environment": "stage",
                "source_stage": "deploy",
            },
            "verdict": {"mode": "agent_only"},
        },
    ]
