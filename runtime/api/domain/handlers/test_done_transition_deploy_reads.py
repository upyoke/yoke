"""In-process integration coverage for the done-transition deployment reads.

Exercises the ``done_transition.*`` deployment and preconditions internal
handlers against a seeded Postgres authority. Each handler wraps the exact
query the engine ran inline; these tests prove the wrapper reads real DB rows
server-side and returns the verdict in its declared response shape. This is
the local / in-process leg of the ALL-MODES contract; the relay leg is
covered by ``test_done_transition_transport``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import done_transition_deploy_reads as reads


def _apply_deploy_schema() -> None:
    """Full core schema + the deployment_runs tables the guards read."""
    from yoke_core.domain import deployment_runs_schema, schema
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_seed_test_helpers import seed_project_identities

    schema.cmd_init()
    conn = connect()
    try:
        seed_project_identities(conn)
    finally:
        conn.close()
    deployment_runs_schema.cmd_init()


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path, _apply_deploy_schema) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _item_env(function, *, item_id, payload=None):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-done-deploy"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload or {},
    )


def _global_env(function, *, payload=None):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-done-deploy"),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def _link_run(conn, run_id, item_id):
    conn.execute(
        "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
        "VALUES (%s, %s, %s)",
        (run_id, item_id, "2026-01-01T00:00:00Z"),
    )
    conn.commit()


def _insert_qa(conn, run_id, check_name, *, blocking, status):
    conn.execute(
        "INSERT INTO deployment_run_qa (run_id, check_name, source, blocking, status) "
        "VALUES (%s, %s, 'flow_default', %s, %s)",
        (run_id, check_name, blocking, status),
    )
    conn.commit()


def _insert_flow(conn, flow_id):
    conn.execute(
        "INSERT INTO deployment_flows (id, project_id, name, stages, created_at) "
        "VALUES (%s, 1, %s, '[]', %s)",
        (flow_id, flow_id, "2026-01-01T00:00:00Z"),
    )
    conn.commit()


class TestRegisteredFlowIds:
    def test_lists_registered_flows_sorted(self, db):
        conn = connect_test_db(db)
        try:
            _insert_flow(conn, "flow-b")
            _insert_flow(conn, "flow-a")
        finally:
            conn.close()
        outcome = reads.handle_registered_flow_ids(
            _global_env("done_transition.registered_flow_ids")
        )
        assert outcome.primary_success, outcome.error
        flow_ids = outcome.result_payload["flow_ids"]
        # The flow catalog may seed hosted flows; the two we inserted are
        # present and the list is sorted (the guard's join order contract).
        assert {"flow-a", "flow-b"} <= set(flow_ids)
        assert flow_ids == sorted(flow_ids)
        reads.RegisteredFlowIdsResponse(**outcome.result_payload)


class TestLatestDeploymentRun:
    def test_returns_latest_by_created_at(self, db):
        item_id = 8510
        conn = connect_test_db(db)
        try:
            insert_deployment_run(
                conn, id="run-old", status="failed",
                created_at="2026-01-01T00:00:00Z",
            )
            insert_deployment_run(
                conn, id="run-new", status="succeeded",
                created_at="2026-02-01T00:00:00Z",
            )
            _link_run(conn, "run-old", item_id)
            _link_run(conn, "run-new", item_id)
        finally:
            conn.close()
        outcome = reads.handle_latest_deployment_run(
            _item_env("done_transition.latest_deployment_run", item_id=item_id)
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload == {"run_id": "run-new", "status": "succeeded"}
        reads.LatestDeploymentRunResponse(**outcome.result_payload)

    def test_empty_when_no_run(self, db):
        outcome = reads.handle_latest_deployment_run(
            _item_env("done_transition.latest_deployment_run", item_id=999903)
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload == {"run_id": "", "status": ""}


class TestRunStage:
    def test_reports_current_stage(self, db):
        conn = connect_test_db(db)
        try:
            insert_deployment_run(
                conn, id="run-stage", status="succeeded",
                current_stage="production-failed",
            )
        finally:
            conn.close()
        outcome = reads.handle_run_stage(
            _global_env("done_transition.run_stage", payload={"run_id": "run-stage"})
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["current_stage"] == "production-failed"
        reads.RunStageResponse(**outcome.result_payload)

    def test_missing_run_is_empty(self, db):
        outcome = reads.handle_run_stage(
            _global_env("done_transition.run_stage", payload={"run_id": "nope"})
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["current_stage"] == ""


class TestRunBlockingQa:
    def test_reports_unsatisfied_blocking_only(self, db):
        conn = connect_test_db(db)
        try:
            insert_deployment_run(conn, id="run-qa", status="succeeded")
            _insert_qa(conn, "run-qa", "smoke", blocking=1, status="failed")
            _insert_qa(conn, "run-qa", "lint", blocking=1, status="passed")
            _insert_qa(conn, "run-qa", "advisory", blocking=0, status="failed")
        finally:
            conn.close()
        outcome = reads.handle_run_blocking_qa(
            _global_env("done_transition.run_blocking_qa",
                        payload={"run_id": "run-qa"})
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["blocking"] == ["smoke (failed)"]
        reads.RunBlockingQaResponse(**outcome.result_payload)


class TestDonePreconditions:
    def test_allows_item_without_deployment_flow(self, db):
        item_id = 8520
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
        finally:
            conn.close()
        outcome = reads.handle_done_preconditions(
            _item_env("done_transition.done_preconditions", item_id=item_id,
                      payload={"deploy_flow": "", "require_plan_verdict": False})
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload == {"allowed": True, "reason": None}
        reads.DonePreconditionsResponse(**outcome.result_payload)

    def test_blocks_registered_flow_missing_deployed_to(self, db):
        item_id = 8521
        conn = connect_test_db(db)
        try:
            insert_deployment_run(conn, id="run-pre", flow="externalwebapp-prod")
            insert_item(
                conn, id=item_id, source=str(seed_human_actor(conn)),
                deployment_flow="externalwebapp-prod",
            )
        finally:
            conn.close()
        outcome = reads.handle_done_preconditions(
            _item_env("done_transition.done_preconditions", item_id=item_id,
                      payload={"deploy_flow": "externalwebapp-prod",
                               "require_plan_verdict": False})
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["allowed"] is False
        assert "deployed_to is empty" in outcome.result_payload["reason"]
