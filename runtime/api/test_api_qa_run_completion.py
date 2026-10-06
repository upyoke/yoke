"""Function-handler completion contracts for QA runs."""

import unittest
from unittest.mock import patch

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.handlers import qa_browser_writes
from runtime.api.fixtures.backlog_inserts import insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.test_api_qa_browser_function import _request, _seed_browser_requirement


class TestQaRunComplete(unittest.TestCase):
    def _add_started_run(self, conn) -> int:
        with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
            outcome = qa_browser_writes.handle_qa_run_add(
                _request(
                    "qa.run.add",
                    TargetRef(kind="qa_requirement", qa_requirement_id=10),
                    payload={"performed_by": "browser_substrate"},
                ),
            )
        return int(outcome.result_payload["qa_run_id"])

    def test_rejects_missing_verdict_and_status(self):
        outcome = qa_browser_writes.handle_qa_run_complete(
            _request(
                "qa.run.complete",
                TargetRef(kind="qa_requirement", qa_requirement_id=10),
                payload={"run_id": 1},
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_rejects_run_of_other_requirement(self):
        with test_database() as conn:
            _seed_browser_requirement(conn)
            insert_qa_requirement(
                conn,
                id=11,
                item_id=42,
                qa_kind="plan_case",
                qa_phase="verification",
                blocking_mode="blocking",
                success_policy="",
            )
            conn.commit()
            run_id = self._add_started_run(conn)
            outcome = qa_browser_writes.handle_qa_run_complete(
                _request(
                    "qa.run.complete",
                    TargetRef(kind="qa_requirement", qa_requirement_id=11),
                    payload={"run_id": run_id, "execution_status": "captured"},
                ),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_captured_completion_updates_row(self):
        with test_database() as conn:
            _seed_browser_requirement(conn)
            run_id = self._add_started_run(conn)
            with patch(
                "yoke_core.domain.qa_events.emit_qa_run_event",
            ) as emit:
                outcome = qa_browser_writes.handle_qa_run_complete(
                    _request(
                        "qa.run.complete",
                        TargetRef(kind="qa_requirement", qa_requirement_id=10),
                        payload={
                            "run_id": run_id,
                            "execution_status": "captured",
                            "capture_degraded_reason": "fixture_no_shot",
                            "raw_result": '{"ok": true}',
                        },
                    ),
                )
            self.assertTrue(outcome.primary_success, outcome.error)
            row = conn.execute(
                "SELECT verdict, execution_status, completed_at "
                "FROM qa_runs WHERE id = %s",
                (run_id,),
            ).fetchone()
        self.assertIsNone(row[0])
        self.assertEqual(row[1], "captured")
        self.assertIsNotNone(row[2])
        self.assertEqual(emit.call_args.kwargs["event_name"], "QARunCaptured")

    def test_agent_undetermined_requires_artifact_before_completion(self):
        with test_database() as conn:
            _seed_browser_requirement(conn)
            insert_qa_requirement(
                conn,
                id=11,
                item_id=42,
                qa_kind="ac_verification",
                qa_phase="verification",
                blocking_mode="blocking",
                success_policy="",
            )
            started = qa_browser_writes.handle_qa_run_add(
                _request(
                    "qa.run.add",
                    TargetRef(kind="qa_requirement", qa_requirement_id=11),
                    payload={"performed_by": "agent"},
                )
            )
            run_id = int(started.result_payload["qa_run_id"])
            payload = {
                "run_id": run_id,
                "verdict": "undetermined",
                "verdict_reason": "The capture shows conflicting states.",
            }
            refused = qa_browser_writes.handle_qa_run_complete(
                _request(
                    "qa.run.complete",
                    TargetRef(kind="qa_requirement", qa_requirement_id=11),
                    payload=payload,
                )
            )
            self.assertEqual(refused.error.code, "qa_undetermined_evidence_required")
            conn.execute(
                "INSERT INTO qa_artifacts "
                "(qa_run_id,artifact_type,created_at) VALUES (%s,'log',NOW())",
                (run_id,),
            )
            conn.commit()
            accepted = qa_browser_writes.handle_qa_run_complete(
                _request(
                    "qa.run.complete",
                    TargetRef(kind="qa_requirement", qa_requirement_id=11),
                    payload=payload,
                )
            )
            self.assertTrue(accepted.primary_success, accepted.error)
