# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

import pytest

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover

from runtime.api.domain.deployment_qa_takeover_identity_test_support import _execution

from runtime.api.domain.deployment_qa_successor_retry_test_support import _record

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict

from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
    validate_deployment_execution_target,
)

from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject

from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution

from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)

from yoke_core.domain.qa_plan_rematerialize_deployment_subject import _pinned_target


def _arrive(conn, *, ready):
    conn.execute(
        "UPDATE deployment_runs n SET status='executing',current_stage=%s,"
        "composition_frozen_at=now(),requirement_snapshot=o.requirement_snapshot "
        "FROM deployment_runs o WHERE n.id=%s AND o.id=%s",
        ("deploy" if ready else takeover.RUN_QA_STAGE, takeover.NEW, takeover.OLD),
    )
    if ready:
        from yoke_core.domain.deployment_stage_receipts import (
            allocate_deployment_stage_receipt,
            complete_deployment_stage_receipt,
        )

        receipt = allocate_deployment_stage_receipt(
            conn,
            run_id=takeover.NEW,
            stage_name="deploy",
            correlation_id="successor-deploy",
            target_kind="persistent_environment",
            executor="test",
            commit=False,
        )
        complete_deployment_stage_receipt(
            conn,
            run_id=takeover.NEW,
            receipt_id=receipt["id"],
            correlation_id=receipt["correlation_id"],
            status="ready",
            target_name="stage",
            observed_url="https://preview.example.test",
            observed_release_lineage=takeover.NEW_LINEAGE,
            executor_receipt="test://successor",
            commit=False,
        )
    conn.execute(
        "UPDATE deployment_runs SET current_stage=%s WHERE id=%s",
        (takeover.RUN_QA_STAGE, takeover.NEW),
    )
    conn.commit()
