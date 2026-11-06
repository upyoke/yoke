# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.dash_post_deploy_done_consumption_test_support import (
    _accept_member_qa,
    _bind_original,
)

from runtime.api.domain.dash_post_deploy_review_isolation_test_support import (
    _insert_dash,
)

from runtime.api.domain.deployment_qa_admission_execution_test_support import (
    _seed_selected_requirement_run,
)

from runtime.api.domain.post_deploy_original_pass_needs_admission_test_support import (
    _record_evidence,
)

from runtime.api.fixtures.backlog_inserts import insert_qa_run

from runtime.api.fixtures.deployment_admitted_case_fixture import succeed_run

from yoke_core.domain.dash_posture_gate import evaluate

from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_case_key,
)

from yoke_core.domain.deployment_qa_source_obligation import (
    source_obligation_consumed,
)

from yoke_core.domain.qa_gates import GateTarget, check_done_gate


def _deliver_intake(conn, *, item_id: int, run_id: str) -> int:
    _insert_dash(conn, item_id=item_id, status="release")
    intake_id = _bind_original(conn, item_id=item_id)
    insert_qa_run(conn, qa_requirement_id=intake_id, verdict="pass")
    _seed_selected_requirement_run(
        conn, run_id=run_id, item_id=item_id, requirement_id=intake_id
    )
    return intake_id
