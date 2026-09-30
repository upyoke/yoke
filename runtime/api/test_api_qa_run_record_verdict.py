"""qa.run.record_verdict refusals and the pass write it records."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.handlers import qa_run

from runtime.api.test_api_qa_function import _request


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

    def test_happy_path_inserts_row(self):
        existing = {
            "qa_kind": "ac_verification",
            "method_id": None,
            "blocking_mode": "non_blocking",
            "waived_at": None,
        }

        class _Cursor:
            # record_verdict reads the inserted id via ``RETURNING id`` +
            # ``cur.fetchone()[0]`` (handlers/qa_run.py); no lastrowid path.
            def fetchone(self):
                return (99,)

        class _Conn:
            def execute(self, sql, params):
                return _Cursor()

            def commit(self):
                pass

            def close(self):
                pass

        with patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()):
            with patch("yoke_core.domain.db_helpers.query_one", return_value=existing):
                with (
                    patch("yoke_core.domain.qa_events.emit_qa_run_event") as emit,
                    patch(
                        "yoke_core.domain.qa_requirement_replacement."
                        "discharge_declared_replacements",
                        return_value=[],
                    ) as discharge,
                ):
                    req = _request(
                        "qa.run.record_verdict",
                        TargetRef(kind="qa_requirement", qa_requirement_id=7),
                        payload={
                            "performed_by": "agent",
                            "verdict": "pass",
                            "raw_result": "all good",
                        },
                    )
                    outcome = qa_run.handle_qa_run_record_verdict(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["qa_run_id"], 99)
        self.assertEqual(outcome.result_payload["verdict"], "pass")
        emit.assert_called_once()
        # The pass discharges replacements on its own transaction.
        self.assertEqual(discharge.call_args.args[1], [7])

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
