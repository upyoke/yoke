# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

import pytest

from runtime.api.domain.deployment_qa_plan_groups_test_support import (
    MEMBERS,
    RUN,
    _attach,
    _seed,
)

from runtime.api.domain.deployment_qa_shared_plans_test_support import _fail

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _plan,
)

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.deployment_qa_plan_ownership import _snapshot

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_run_stage_entry import set_current_stage

from yoke_core.domain.project_identity import render_item_ref

from yoke_core.domain.qa_item_deployment_request import resolve_item_deployment_request

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

from yoke_core.domain.qa_plan_management import QaPlanError, replace_plan_cases

from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)

from yoke_core.domain.qa_requirement_correction_selection import (
    resolve_correction_selection,
)

from yoke_core.domain.qa_requirement_replacement import declare_replacements


def _correct(conn, plan, label="corrected"):
    replace_plan_cases(
        conn,
        plan_id=plan,
        cases=[
            {
                "case_key": "command-smoke",
                "position": 1,
                "method_id": "command",
                "instructions": f"Run the {label} member probe.",
                "expected_outcome": "The corrected probe passes.",
                "method_config": {"command": f"echo {label}"},
            }
        ],
    )
