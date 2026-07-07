"""Unit tests for the qa read handlers —
qa.requirement.{list,get}, qa.run.{list,get}, qa.gate_summary.run.

Direct handler calls against the isolated Postgres fixture (same
pattern as ``runtime/api/test_api_qa_browser_evidence.py``).
"""

from __future__ import annotations

import unittest

from yoke_core.domain.handlers import qa_reads
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.fixtures.backlog_inserts import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.pg_testdb import test_database


def _request(
    function_id: str, target: TargetRef, payload=None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=target,
        payload=payload or {},
    )


def _seed_two_items(conn) -> None:
    insert_item(conn, id=42, title="A", status="implementing")
    insert_item(conn, id=43, title="B", status="implementing")
    insert_qa_requirement(
        conn, id=10, item_id=42, qa_kind="ac_verification",
        qa_phase="verification",
    )
    insert_qa_requirement(
        conn, id=11, item_id=43, qa_kind="ac_verification",
        qa_phase="verification",
    )
    conn.commit()


class TestRequirementList(unittest.TestCase):
    def test_item_target_filters_rows(self):
        with test_database() as conn:
            _seed_two_items(conn)
            outcome = qa_reads.handle_qa_requirement_list(
                _request(
                    "qa.requirement.list",
                    TargetRef(kind="item", item_id=42),
                ),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        rows = outcome.result_payload["rows"]
        self.assertEqual([r["id"] for r in rows], [10])
        self.assertEqual(rows[0]["qa_kind"], "ac_verification")

    def test_epic_filter_via_payload(self):
        with test_database() as conn:
            insert_item(conn, id=50, title="E", type="epic", status="planning")
            insert_qa_requirement(
                conn, id=20, item_id=None, epic_id=50, task_num=2,
                qa_kind="implementation_review", qa_phase="verification",
            )
            conn.commit()
            outcome = qa_reads.handle_qa_requirement_list(
                _request(
                    "qa.requirement.list",
                    TargetRef(kind="global"),
                    payload={"epic_id": 50},
                ),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        rows = outcome.result_payload["rows"]
        self.assertEqual([r["id"] for r in rows], [20])
        self.assertEqual(rows[0]["epic_id"], 50)
        self.assertEqual(rows[0]["task_num"], 2)

    def test_unfiltered_global_lists_all(self):
        with test_database() as conn:
            _seed_two_items(conn)
            outcome = qa_reads.handle_qa_requirement_list(
                _request("qa.requirement.list", TargetRef(kind="global")),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        self.assertEqual(len(outcome.result_payload["rows"]), 2)


class TestRequirementGet(unittest.TestCase):
    def test_returns_one_row(self):
        with test_database() as conn:
            _seed_two_items(conn)
            outcome = qa_reads.handle_qa_requirement_get(
                _request(
                    "qa.requirement.get",
                    TargetRef(kind="qa_requirement", qa_requirement_id=11),
                ),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        requirement = outcome.result_payload["requirement"]
        self.assertEqual(requirement["id"], 11)
        self.assertEqual(requirement["item_id"], 43)

    def test_missing_target_rejected(self):
        outcome = qa_reads.handle_qa_requirement_get(
            _request("qa.requirement.get", TargetRef(kind="global")),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_unknown_id_not_found(self):
        with test_database() as conn:
            _seed_two_items(conn)
            outcome = qa_reads.handle_qa_requirement_get(
                _request(
                    "qa.requirement.get",
                    TargetRef(kind="qa_requirement", qa_requirement_id=9999),
                ),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "not_found")


class TestRunList(unittest.TestCase):
    def test_filters_by_requirement_target(self):
        with test_database() as conn:
            _seed_two_items(conn)
            insert_qa_run(
                conn, qa_requirement_id=10, qa_kind="ac_verification",
                verdict="pass",
            )
            insert_qa_run(
                conn, qa_requirement_id=11, qa_kind="ac_verification",
                verdict="fail",
            )
            conn.commit()
            outcome = qa_reads.handle_qa_run_list(
                _request(
                    "qa.run.list",
                    TargetRef(kind="qa_requirement", qa_requirement_id=10),
                ),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        rows = outcome.result_payload["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["qa_requirement_id"], 10)
        self.assertEqual(rows[0]["verdict"], "pass")
        self.assertIn("execution_status", rows[0])

    def test_global_lists_all_runs(self):
        with test_database() as conn:
            _seed_two_items(conn)
            insert_qa_run(conn, qa_requirement_id=10, qa_kind="ac_verification")
            insert_qa_run(conn, qa_requirement_id=11, qa_kind="ac_verification")
            conn.commit()
            outcome = qa_reads.handle_qa_run_list(
                _request("qa.run.list", TargetRef(kind="global")),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        self.assertEqual(len(outcome.result_payload["rows"]), 2)


class TestRunGet(unittest.TestCase):
    def test_returns_one_row_by_run_id(self):
        with test_database() as conn:
            _seed_two_items(conn)
            run_row = insert_qa_run(
                conn, qa_requirement_id=10, qa_kind="ac_verification",
                verdict="pass",
            )
            run_id = int(run_row["id"])
            conn.commit()
            outcome = qa_reads.handle_qa_run_get(
                _request(
                    "qa.run.get",
                    TargetRef(kind="global"),
                    payload={"run_id": run_id},
                ),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        run = outcome.result_payload["run"]
        self.assertEqual(run["id"], run_id)
        self.assertEqual(run["qa_requirement_id"], 10)
        self.assertEqual(run["verdict"], "pass")
        self.assertIn("execution_status", run)

    def test_missing_run_id_rejected(self):
        outcome = qa_reads.handle_qa_run_get(
            _request("qa.run.get", TargetRef(kind="global")),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertEqual(outcome.error.jsonpath, "$.payload.run_id")

    def test_unknown_run_id_not_found(self):
        with test_database() as conn:
            _seed_two_items(conn)
            outcome = qa_reads.handle_qa_run_get(
                _request(
                    "qa.run.get",
                    TargetRef(kind="global"),
                    payload={"run_id": 9999},
                ),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "not_found")


class TestGateSummary(unittest.TestCase):
    def test_unsatisfied_then_satisfied_for_item(self):
        with test_database() as conn:
            _seed_two_items(conn)
            request = _request(
                "qa.gate_summary.run",
                TargetRef(kind="item", item_id=42),
                payload={"transition": "reviewed-implementation"},
            )
            before = qa_reads.handle_qa_gate_summary(request)
            insert_qa_run(
                conn, qa_requirement_id=10, qa_kind="ac_verification",
                verdict="pass",
            )
            conn.commit()
            after = qa_reads.handle_qa_gate_summary(request)
        self.assertTrue(before.primary_success, before.error)
        self.assertFalse(before.result_payload["satisfied"])
        self.assertEqual(
            before.result_payload["blocking_unsatisfied_count"], 1,
        )
        self.assertTrue(after.primary_success, after.error)
        self.assertTrue(after.result_payload["satisfied"])
        self.assertEqual(after.result_payload["requirements"][0]["id"], 10)

    def test_epic_task_target(self):
        with test_database() as conn:
            insert_item(conn, id=50, title="E", type="epic", status="planning")
            insert_qa_requirement(
                conn, id=20, item_id=None, epic_id=50, task_num=2,
                qa_kind="implementation_review", qa_phase="verification",
            )
            conn.commit()
            outcome = qa_reads.handle_qa_gate_summary(
                _request(
                    "qa.gate_summary.run",
                    TargetRef(kind="epic_task", epic_id=50, task_num=2),
                    payload={"transition": "implemented"},
                ),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        self.assertFalse(outcome.result_payload["satisfied"])
        self.assertEqual(outcome.result_payload["transition"], "implemented")

    def test_invalid_transition_rejected(self):
        outcome = qa_reads.handle_qa_gate_summary(
            _request(
                "qa.gate_summary.run",
                TargetRef(kind="item", item_id=42),
                payload={"transition": "done"},
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_missing_target_rejected(self):
        outcome = qa_reads.handle_qa_gate_summary(
            _request(
                "qa.gate_summary.run",
                TargetRef(kind="global"),
                payload={"transition": "implemented"},
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")


if __name__ == "__main__":
    unittest.main()
