"""Unit tests for qa.requirement.{add,add_batch}.

Direct handler calls against the isolated Postgres fixture, plus
registry-coherence assertions for the claim gating the dispatcher
applies (writes are item-claim-gated, reads are not).
"""

from __future__ import annotations

import unittest

from yoke_core.domain.handlers import qa_requirement_create
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


class TestRequirementAdd(unittest.TestCase):
    def test_inserts_item_attached_row(self):
        with test_database() as conn:
            insert_item(conn, id=42, title="T", status="implementing")
            conn.commit()
            outcome = qa_requirement_create.handle_qa_requirement_add(
                _request(
                    "qa.requirement.add", 42,
                    {
                        "qa_kind": "ac_verification",
                        "qa_phase": "verification",
                        "requirement_source": "ac_derived",
                        "success_policy": "AC-1 verified end to end",
                    },
                ),
            )
            self.assertTrue(outcome.primary_success, outcome.error)
            req_id = outcome.result_payload["requirement_id"]
            row = conn.execute(
                "SELECT item_id, qa_kind, qa_phase, blocking_mode, "
                "requirement_source FROM qa_requirements WHERE id = %s",
                (req_id,),
            ).fetchone()
        self.assertEqual(int(row[0]), 42)
        self.assertEqual(row[1], "ac_verification")
        self.assertEqual(row[2], "verification")
        self.assertEqual(row[3], "blocking")
        self.assertEqual(row[4], "ac_derived")

    def test_normalizes_retired_vocab(self):
        with test_database() as conn:
            insert_item(conn, id=42, title="T", status="implementing")
            conn.commit()
            outcome = qa_requirement_create.handle_qa_requirement_add(
                _request(
                    "qa.requirement.add", 42,
                    {"qa_kind": "review", "qa_phase": "validation"},
                ),
            )
            self.assertTrue(outcome.primary_success, outcome.error)
            row = conn.execute(
                "SELECT qa_kind, qa_phase FROM qa_requirements WHERE id = %s",
                (outcome.result_payload["requirement_id"],),
            ).fetchone()
        self.assertEqual(row[0], "implementation_review")
        self.assertEqual(row[1], "verification")

    def test_missing_target_rejected(self):
        outcome = qa_requirement_create.handle_qa_requirement_add(
            _request(
                "qa.requirement.add", None,
                {"qa_kind": "ac_verification", "qa_phase": "verification"},
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_browser_kind_requires_steps_policy(self):
        outcome = qa_requirement_create.handle_qa_requirement_add(
            _request(
                "qa.requirement.add", 42,
                {"qa_kind": "browser_smoke", "qa_phase": "verification"},
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertEqual(outcome.error.jsonpath, "$.payload.success_policy")

    def test_invalid_requirement_source_rejected(self):
        outcome = qa_requirement_create.handle_qa_requirement_add(
            _request(
                "qa.requirement.add", 42,
                {
                    "qa_kind": "ac_verification",
                    "qa_phase": "verification",
                    "requirement_source": "nonsense",
                },
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_invalid_blocking_mode_rejected_typed(self):
        """The DB CHECK enum is pre-validated — a bad blocking_mode gets a
        typed payload_invalid naming the allowed values, never a raw
        CheckViolation / HTTP 500."""
        outcome = qa_requirement_create.handle_qa_requirement_add(
            _request(
                "qa.requirement.add", 42,
                {
                    "qa_kind": "ac_verification",
                    "qa_phase": "verification",
                    "blocking_mode": "advisory",
                },
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertIn("non_blocking", outcome.error.message)
        self.assertIn("advisory", outcome.error.message)


class TestRequirementAddBatch(unittest.TestCase):
    def test_inserts_rows_in_one_batch(self):
        with test_database() as conn:
            insert_item(conn, id=42, title="T", status="implementing")
            conn.commit()
            outcome = qa_requirement_create.handle_qa_requirement_add_batch(
                _request(
                    "qa.requirement.add_batch", 42,
                    {
                        "rows": [
                            {
                                "qa_kind": "ac_verification",
                                "qa_phase": "verification",
                            },
                            {
                                "qa_kind": "browser_smoke",
                                "qa_phase": "verification",
                                "success_policy": (
                                    '{"steps": [{"action": "navigate", '
                                    '"route": "/"}]}'
                                ),
                            },
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
                    "qa.requirement.add_batch", 42,
                    {
                        "rows": [
                            {
                                "qa_kind": "ac_verification",
                                "qa_phase": "verification",
                            },
                            # Browser kind without the required steps JSON.
                            {
                                "qa_kind": "browser_smoke",
                                "qa_phase": "verification",
                            },
                        ],
                    },
                ),
            )
            self.assertFalse(outcome.primary_success)
            self.assertEqual(outcome.error.code, "payload_invalid")
            self.assertIn("rows[1]", outcome.error.jsonpath)
            count = conn.execute(
                "SELECT COUNT(*) FROM qa_requirements WHERE item_id = 42",
            ).fetchone()
        self.assertEqual(int(count[0]), 0)

    def test_row_naming_other_item_rejected(self):
        outcome = qa_requirement_create.handle_qa_requirement_add_batch(
            _request(
                "qa.requirement.add_batch", 42,
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
                "qa.requirement.add_batch", 42,
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


class TestRegistryClaimGating(unittest.TestCase):
    """The dispatcher applies claim checks from registry metadata — the
    qa CRUD writes must be item-claim-gated and the reads must not be."""

    def test_writes_item_gated_reads_open(self):
        from yoke_core.domain import yoke_function_registry
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )

        register_all_handlers()
        entries = {
            e.function_id: e for e in yoke_function_registry.list_entries()
        }
        for fid in ("qa.requirement.add", "qa.requirement.add_batch"):
            self.assertEqual(entries[fid].claim_required_kind, "item", fid)
            self.assertIn("claim_required", entries[fid].guardrails, fid)
            self.assertEqual(
                entries[fid].side_effects, ("qa_requirements_insert",), fid,
            )
        for fid in (
            "qa.requirement.list", "qa.requirement.get", "qa.run.list",
            "qa.gate_summary.run",
        ):
            self.assertIsNone(entries[fid].claim_required_kind, fid)
            self.assertEqual(entries[fid].side_effects, (), fid)


if __name__ == "__main__":
    unittest.main()
