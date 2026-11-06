"""qa.run.record_verdict refusals and the pass write it records."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.handlers import qa_run

from runtime.api.api_qa_browser_function_test_support import (_request)


class TestQaRunRecordVerdict(unittest.TestCase):
    def test_rejects_invalid_verdict(self):
        req = _request(
            "qa.run.record_verdict",
            TargetRef(kind="qa_requirement", qa_requirement_id=7),
            payload={"performed_by": "agent", "verdict": "maybe"},
        )
        outcome = qa_run.handle_qa_run_record_verdict(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_rejects_agent_for_browser_method(self):
        existing = {"qa_kind": "plan_case", "method_id": "browser-check"}

        class _Conn:
            def close(self):
                pass

        with patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()):
            with patch("yoke_core.domain.db_helpers.query_one", return_value=existing):
                req = _request(
                    "qa.run.record_verdict",
                    TargetRef(kind="qa_requirement", qa_requirement_id=7),
                    payload={"performed_by": "agent", "verdict": "pass"},
                )
                outcome = qa_run.handle_qa_run_record_verdict(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "policy_violation")

    def test_agent_undetermined_refuses_without_artifact_surface(self):
        existing = {"qa_kind": "ac_verification", "method_id": None}

        class _Conn:
            def execute(self, _sql, _params=()):
                raise AssertionError("refusal must precede the verdict insert")

            def close(self):
                pass

        with patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()):
            with patch("yoke_core.domain.db_helpers.query_one", return_value=existing):
                req = _request(
                    "qa.run.record_verdict",
                    TargetRef(kind="qa_requirement", qa_requirement_id=7),
                    payload={
                        "performed_by": "agent",
                        "verdict": "undetermined",
                        "verdict_reason": "The log omits the final assertion.",
                    },
                )
                outcome = qa_run.handle_qa_run_record_verdict(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "qa_undetermined_evidence_required")
        self.assertIn("Attach at least one qa_artifacts row", outcome.error.message)


def test_record_verdict_writes_real_pass_on_production_schema(test_db):
    from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement

    insert_item(test_db, id=901)
    requirement = insert_qa_requirement(
        test_db, item_id=901, blocking_mode="non_blocking"
    )
    outcome = qa_run.handle_qa_run_record_verdict(
        _request(
            "qa.run.record_verdict",
            TargetRef(kind="qa_requirement", qa_requirement_id=int(requirement["id"])),
            payload={
                "performed_by": "agent",
                "verdict": "pass",
                "raw_result": "all good",
            },
        )
    )
    assert outcome.primary_success, outcome.error
    run_id = outcome.result_payload["qa_run_id"]
    row = test_db.execute(
        "SELECT verdict,raw_result FROM qa_runs WHERE id=%s", (run_id,)
    ).fetchone()
    assert row[0] == "pass"
    assert row[1] == "all good"
