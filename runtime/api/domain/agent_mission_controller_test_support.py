# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from types import SimpleNamespace

import pytest

from runtime.api.domain.qa_plan_standalone_execution_test_support import _begin

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_contracts.qa_case_starting_state import (
    needs_test_machine,
    StartingStateError,
    normalize_starting_state,
)

from yoke_core.domain.agent_mission_brief import _walker_dispatch

from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin

from yoke_core.domain.machine_reset_debt import record_execution_reset_debt

from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

from yoke_core.domain.qa_plan_execution_state import (
    lock_plan_execution,
    finish_plan_execution,
)

from yoke_core.domain.qa_plan_review import begin_plan_review


def _mission(conn, *, with_host=False):
    plan = create_plan(
        conn, project="yoke", slug="manual-proof", name="Controller exploration"
    )
    cases = [
        {
            "case_key": "controller",
            "position": 1,
            "method_id": "exploratory-mission",
            "instructions": "Explore controller evidence",
            "expected_outcome": "Rank findings",
            "method_config": {"executor": "informed_subagent"},
        }
    ]
    if with_host:
        cases.insert(
            0,
            {
                "case_key": "host",
                "position": 1,
                "method_id": "machine-state-check",
                "instructions": "Check host",
                "expected_outcome": "Assertion passes",
                "host_baselines": ["fresh-host"],
                "method_config": {
                    "assertions": [{"argv": ["/usr/bin/true"]}],
                    "os": "macos",
                    "test_machine": "mac-mini-lab",
                },
            },
        )
        cases[1]["position"] = 2
    replace_plan_cases(conn, plan_id=plan["id"], cases=cases)
    conn.commit()
    return _begin(conn, test_machine=None if with_host else "unused-run-pin")
