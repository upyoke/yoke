"""Function-handler completion contracts for QA runs."""

import json
import unittest
from unittest.mock import patch

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain import served_revision_probe as probe
from yoke_core.domain.qa_execution_environment_target import resolve_plan_execution_target
from yoke_core.domain.qa_plan_management import create_plan
from yoke_core.domain.handlers import qa_browser_writes
from runtime.api.domain.qa_requirement_target_rebind_test_support import _yoke_development
from runtime.api.fixtures.backlog_inserts import insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.api_qa_browser_function_test_support import (
    _request,
    _seed_browser_requirement,
)


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

    def test_unobservable_build_refuses_run_add_and_complete(self):
        with test_database() as conn:
            _seed_browser_requirement(conn)
            environment_id = _yoke_development(conn)
            conn.execute(
                "UPDATE environments SET url=%s,settings=%s WHERE id=%s",
                ("https://qa.example.test", '{"qa":{"identity_path":"/served-build"}}', environment_id),
            )
            plan = create_plan(conn, project="yoke", slug="build-observation", target_environment=str(environment_id))
            target = resolve_plan_execution_target(conn, plan_id=plan["id"])
            conn.execute(
                "UPDATE qa_requirements SET execution_target_json=%s WHERE id=10",
                (json.dumps(target),),
            )
            conn.commit()

            requirement = TargetRef(kind="qa_requirement", qa_requirement_id=10)
            with patch.object(probe, "fetch_served_revision", return_value=probe.ServedRevisionRead(error="offline")):
                refused_add = qa_browser_writes.handle_qa_run_add(
                    _request("qa.run.add", requirement, payload={"performed_by": "browser_substrate"}),
                )
            self.assertEqual(refused_add.error.code, "qa_execution_target_refused")
            self.assertIn("served_build_unobservable", refused_add.error.message)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0], 0)

            with patch.object(probe, "fetch_served_revision", return_value=probe.ServedRevisionRead(status=200, body="a" * 40)):
                run_id = self._add_started_run(conn)
            with patch.object(probe, "fetch_served_revision", return_value=probe.ServedRevisionRead(error="offline")):
                refused_complete = qa_browser_writes.handle_qa_run_complete(
                    _request("qa.run.complete", requirement, payload={"run_id": run_id, "verdict": "pass"}),
                )
            self.assertEqual(refused_complete.error.code, "qa_execution_target_refused")
            self.assertIn("served_build_unobservable", refused_complete.error.message)
            row = conn.execute("SELECT verdict,completed_at FROM qa_runs WHERE id=%s", (run_id,)).fetchone()
            self.assertEqual(tuple(row), (None, None))

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
