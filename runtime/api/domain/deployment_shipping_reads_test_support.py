# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

import sys

from unittest.mock import patch

from collections import Counter

from time import perf_counter

from yoke_contracts.api.function_call import FunctionCallResponse

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)

from runtime.api.domain.deployment_qa_shared_plans_test_support import _fail

from yoke_core.domain.deployment_qa_run_acceptance import (
    current_item_qa,
    member_qa_standings,
)

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution


class CountedConnection:
    def __init__(self, conn):
        self.conn = conn
        self.queries = Counter()
        self.callers = Counter()

    def execute(self, sql, params=()):
        self.queries[sql] += 1
        caller = sys._getframe(1)
        while caller.f_globals["__name__"] == "yoke_core.domain.db_helpers":
            caller = caller.f_back
        self.callers[f"{caller.f_globals['__name__']}.{caller.f_code.co_name}"] += 1
        return self.conn.execute(sql, params)

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self.conn, name)
