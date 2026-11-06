# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import pytest

from runtime.api.fixtures.statement_counter import CountingConnection

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _plan,
    _seed_run,
    _stages,
)

from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.handlers.deployment_run_execution import _member_rows


def _seed(conn, run_id, members, *, materialized=True):
    stages = _stages(_plan(conn, run_id))
    _seed_run(conn, run_id=run_id, stages=stages, members=members)
    for member in members if materialized else ():
        materialize_deployment_qa_stage(
            conn,
            deployment_run_id=run_id,
            deployment_stage="item-qa",
            deployment_member_item_id=member,
        )
    return stages[1]
