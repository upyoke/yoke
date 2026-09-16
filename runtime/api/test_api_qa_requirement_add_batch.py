"""Several item-attached cases inserted for ONE item in one transaction.

``qa.requirement.add_batch`` validates every row before the transaction
opens and rejects any row naming a different item or a non-item
attachment. Sibling of
:mod:`runtime.api.test_api_qa_requirement_create_function`, which covers
single-case authoring.
"""

from __future__ import annotations

import unittest

from yoke_core.domain.handlers import qa_requirement_create
from yoke_core.domain.qa_workflow_binding_validation import (
    item_transition_for_gate,
)
from yoke_core.domain.workflow_gate_catalog import GATE_QA_VERIFICATION
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database


def _request(function_id: str, item_id, payload) -> FunctionCallRequest:
    target = (
        TargetRef(kind="item", item_id=item_id)
        if item_id is not None
        else TargetRef(kind="global")
    )
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=target,
        payload=payload,
    )


def _bound_row(conn, item_id: int, payload: dict) -> dict:
    return {
        **payload,
        "workflow_transition_id": item_transition_for_gate(
            conn,
            item_id=item_id,
            gate_id=GATE_QA_VERIFICATION,
        ),
    }


class TestRequirementAddBatch(unittest.TestCase):
    def test_inserts_rows_in_one_batch(self):
        with test_database() as conn:
            insert_item(conn, id=42, title="T", status="implementing")
            conn.commit()
            outcome = qa_requirement_create.handle_qa_requirement_add_batch(
                _request(
                    "qa.requirement.add_batch",
                    42,
                    {
                        "rows": [
                            _bound_row(
                                conn,
                                42,
                                {
                                    "qa_kind": "ac_verification",
                                    "qa_phase": "verification",
                                },
                            ),
                            _bound_row(
                                conn,
                                42,
                                {
                                    "method_id": "browser-check",
                                    "qa_phase": "verification",
                                    "instructions": "Check the page.",
                                    "expected_outcome": "The page is ready.",
                                    "method_config": {
                                        "steps": [
                                            {"action": "navigate", "route": "/"},
                                            {
                                                "action": "assert",
                                                "target": "main",
                                                "check": "visible",
                                            },
                                        ],
                                    },
                                },
                            ),
                        ],
                    },
                ),
            )
            self.assertTrue(outcome.primary_success, outcome.error)
            ids = outcome.result_payload["requirement_ids"]
            self.assertEqual(len(ids), 2)
            count = conn.execute(
                "SELECT COUNT(*) FROM qa_requirements WHERE item_id = 42",
            ).fetchone()
        self.assertEqual(int(count[0]), 2)

    def test_invalid_row_rejects_whole_batch_pre_transaction(self):
        with test_database() as conn:
            insert_item(conn, id=42, title="T", status="implementing")
            conn.commit()
            outcome = qa_requirement_create.handle_qa_requirement_add_batch(
                _request(
                    "qa.requirement.add_batch",
                    42,
                    {
                        "rows": [
                            _bound_row(
                                conn,
                                42,
                                {
                                    "qa_kind": "ac_verification",
                                    "qa_phase": "verification",
                                },
                            ),
                            # Browser method without its case contract.
                            _bound_row(
                                conn,
                                42,
                                {
                                    "method_id": "browser-check",
                                    "qa_phase": "verification",
                                },
                            ),
                        ],
                    },
                ),
            )
            self.assertFalse(outcome.primary_success)
            self.assertEqual(outcome.error.code, "payload_invalid")
            self.assertEqual(
                outcome.error.jsonpath,
                "$.payload.rows[1].instructions",
            )
            count = conn.execute(
                "SELECT COUNT(*) FROM qa_requirements WHERE item_id = 42",
            ).fetchone()
        self.assertEqual(int(count[0]), 0)

    def test_row_naming_other_item_rejected(self):
        outcome = qa_requirement_create.handle_qa_requirement_add_batch(
            _request(
                "qa.requirement.add_batch",
                42,
                {
                    "rows": [
                        {
                            "item_id": 43,
                            "qa_kind": "ac_verification",
                            "qa_phase": "verification",
                        },
                    ],
                },
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertIn("one batch covers one item", outcome.error.message)

    def test_epic_attachment_rejected(self):
        outcome = qa_requirement_create.handle_qa_requirement_add_batch(
            _request(
                "qa.requirement.add_batch",
                42,
                {
                    "rows": [
                        {
                            "epic_id": 50,
                            "task_num": 1,
                            "qa_kind": "implementation_review",
                            "qa_phase": "verification",
                        },
                    ],
                },
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_empty_rows_rejected(self):
        outcome = qa_requirement_create.handle_qa_requirement_add_batch(
            _request("qa.requirement.add_batch", 42, {"rows": []}),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")


if __name__ == "__main__":
    unittest.main()
