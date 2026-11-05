# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

import pytest

from runtime.api.domain.qa_abort_reset_test_support import failed_restore, operation  # noqa: F401

from runtime.api.fixtures.dispatch_actor import register_session_actor

from runtime.api.fixtures.pg_testdb import test_database

from runtime.api.fixtures.qa_captured_plan_review_fixture import captured_plan_review

from yoke_contracts.api.function_call import ActorContext

from yoke_core.domain.coordination_claims import acquire, get_claim, release

from yoke_core.domain.db_helpers import query_one

from yoke_core.domain.handlers.machine_qa_operation import (
    handle_operation_begin,
    handle_operation_submit,
)

from yoke_core.domain.project_identity import resolve_project_id

from yoke_core.domain.qa_plan_execution_authority import require_plan_execution_owner

from yoke_core.domain.qa_plan_execution_reconcile import reconcile_execution

from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    lock_plan_execution,
)

from yoke_core.domain.qa_plan_review import begin_plan_review

from yoke_core.domain.schema_init_tables import create_governed_tables

from yoke_core.domain.work_claim_targets import make_qa_admission_target

STEERING = "steering-session"

REASON = "owner ended before settling its walk"


def _stale(conn, execution_id):
    conn.execute(
        "UPDATE qa_plan_executions SET heartbeat_at='2000-01-01T00:00:00Z' WHERE id=%s",
        (execution_id,),
    )
    conn.commit()


def _reconcile(conn, execution_id, session_id=STEERING):
    return reconcile_execution(
        conn,
        execution_id,
        project_id=resolve_project_id(conn, "yoke"),
        actor_id="2",
        session_id=session_id,
        reason=REASON,
    )


def _awaiting_review(conn, item_id):
    """A full captured walk whose review bundle is pending."""
    execution, requirement, capture = captured_plan_review(conn, item_id)
    create_governed_tables(conn)
    bundle = begin_plan_review(conn, execution)
    return lock_plan_execution(conn, execution["id"]), bundle, capture


def _without_artifacts(conn, bundle_id):
    """The prod shape: a mission walker that never attached its proof."""
    row = query_one(
        conn, "SELECT bundle_json FROM qa_plan_review_bundles WHERE id=%s", (bundle_id,)
    )
    payload = json.loads(row["bundle_json"])
    for case in payload["cases"]:
        case["artifacts"] = []
        case["capture_degraded_reason"] = (
            "agent_mission_docket:walker_artifacts_not_yet_attached"
        )
    conn.execute(
        "UPDATE qa_plan_review_bundles SET bundle_json=%s WHERE id=%s",
        (json.dumps(payload), bundle_id),
    )
    conn.commit()


def _receipt(conn, reconciliation_id):
    return query_one(
        conn,
        "SELECT * FROM qa_plan_execution_reconciliations WHERE id=%s",
        (reconciliation_id,),
    )
