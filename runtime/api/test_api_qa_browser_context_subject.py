"""qa.browser_context.get reads whichever subject its case names.

A materialized Browser case is scoped to exactly one subject: the item it
verifies, or the deployment run it verifies. The read scopes its
requirement lookup to that subject and refuses a target naming both or
neither, so a run-scoped case never has to borrow an item to be readable.
"""

from __future__ import annotations

import unittest

from yoke_core.domain.handlers import qa_browser
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.fixtures.backlog_inserts import (
    insert_deployment_run,
    insert_item,
    insert_qa_requirement,
)
from runtime.api.fixtures.pg_testdb import test_database


DEPLOYMENT_RUN_ID = "run-20260101-001"


def _request(target: TargetRef, payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.browser_context.get",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=target,
        payload=payload or {},
    )


def _seed_deployment_run_case(conn, *, req_id: int = 20) -> None:
    insert_deployment_run(conn, id=DEPLOYMENT_RUN_ID, status="executing")
    insert_qa_requirement(
        conn,
        id=req_id,
        item_id=None,
        deployment_run_id=DEPLOYMENT_RUN_ID,
        qa_kind="plan_case",
        success_policy='{"id":"all-pass","params":{}}',
        method_id="browser-check",
        instructions="Open the approval pages and assert they render.",
        expected_outcome="The pages render.",
        method_config=(
            '{"base_url":"http://localhost:9",'
            '"steps":[{"action":"navigate","route":"/"}]}'
        ),
    )
    conn.commit()


class TestQaBrowserContextSubject(unittest.TestCase):
    def test_deployment_run_target_returns_its_case(self):
        with test_database() as conn:
            _seed_deployment_run_case(conn)
            outcome = qa_browser.handle_qa_browser_context_get(
                _request(
                    TargetRef(
                        kind="deployment_run",
                        deployment_run_id=DEPLOYMENT_RUN_ID,
                    ),
                    payload={"project": "yoke", "requirement_id": 20},
                ),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        result = outcome.result_payload
        self.assertIsNone(result["item_id"])
        self.assertEqual(result["deployment_run_id"], DEPLOYMENT_RUN_ID)
        self.assertEqual([r["id"] for r in result["requirements"]], [20])

    def test_item_target_does_not_return_a_deployment_run_case(self):
        with test_database() as conn:
            insert_item(conn, id=42, title="T", status="reviewing-implementation")
            _seed_deployment_run_case(conn)
            outcome = qa_browser.handle_qa_browser_context_get(
                _request(
                    TargetRef(kind="item", item_id=42),
                    payload={"project": "yoke", "requirement_id": 20},
                ),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        self.assertEqual(outcome.result_payload["requirements"], [])

    def test_rejects_a_target_naming_both_subjects(self):
        outcome = qa_browser.handle_qa_browser_context_get(
            _request(
                TargetRef(
                    kind="item",
                    item_id=42,
                    deployment_run_id=DEPLOYMENT_RUN_ID,
                ),
                payload={"project": "yoke", "requirement_id": 20},
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")
        self.assertIn("exactly one subject", outcome.error.message)


if __name__ == "__main__":
    unittest.main()
