# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from unittest import mock

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)

from yoke_core.domain.decision_request_resolution import resolve_decision_request

from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
)

from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

from yoke_core.domain.qa_plan_review import begin_plan_review

from yoke_core.domain.qa_plan_review_submission import submit_plan_review


def _human_actor(test_db, actor_id: int) -> None:
    test_db.execute(
        "INSERT INTO actors(id,kind,created_at) VALUES "
        "(%s,'human','2026-09-14T00:00:00Z') ON CONFLICT(id) DO NOTHING",
        (actor_id,),
    )
