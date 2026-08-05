"""Project isolation for ``qa.run.get`` handler reads."""

from __future__ import annotations

import unittest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import qa_reads
from runtime.api.fixtures.backlog_inserts import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.pg_testdb import test_database


def _request(*, run_id: int, project: str | None = None) -> FunctionCallRequest:
    payload: dict = {"run_id": run_id}
    target_project = None
    if project is not None:
        payload["project"] = project
        target_project = project
    return FunctionCallRequest(
        function="qa.run.get",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="global", project_id=target_project),
        payload=payload,
    )


class TestQaRunGetProjectScope(unittest.TestCase):
    def test_matching_project_returns_run(self) -> None:
        with test_database() as conn:
            insert_item(conn, id=42, title="A", project="yoke")
            insert_qa_requirement(
                conn,
                id=10,
                item_id=42,
                qa_kind="ac_verification",
                qa_phase="verification",
            )
            run_row = insert_qa_run(
                conn,
                qa_requirement_id=10,
                qa_kind="ac_verification",
                verdict="pass",
            )
            run_id = int(run_row["id"])
            conn.commit()
            outcome = qa_reads.handle_qa_run_get(
                _request(run_id=run_id, project="yoke"),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        self.assertEqual(outcome.result_payload["run"]["id"], run_id)

    def test_wrong_project_refused(self) -> None:
        with test_database() as conn:
            insert_item(conn, id=42, title="A", project="yoke")
            insert_item(conn, id=43, title="B", project="externalwebapp")
            insert_qa_requirement(
                conn,
                id=10,
                item_id=42,
                qa_kind="ac_verification",
                qa_phase="verification",
            )
            run_row = insert_qa_run(
                conn,
                qa_requirement_id=10,
                qa_kind="ac_verification",
                verdict="fail",
            )
            run_id = int(run_row["id"])
            conn.commit()
            outcome = qa_reads.handle_qa_run_get(
                _request(run_id=run_id, project="externalwebapp"),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "project_mismatch")
