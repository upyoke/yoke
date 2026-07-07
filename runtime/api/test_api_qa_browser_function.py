"""Unit tests for the browser-QA function family.

``qa.browser_context.get`` + ``qa.run.add`` + ``qa.run.complete`` +
``qa.artifact.add`` — the DB legs of the browser-QA orchestrator. Handlers
run against the isolated Postgres fixture (the orchestrator-side seam test
asserting the dispatcher wiring lives in
``runtime/api/domain/test_browser_qa_transport.py``).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_core.domain.handlers import qa_browser, qa_browser_writes
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database


def _request(function_id: str, target: TargetRef, payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=target,
        payload=payload or {},
    )


def _seed_browser_requirement(conn, *, req_id: int = 10, item_id: int = 42,
                              qa_kind: str = "browser_smoke") -> None:
    insert_item(conn, id=item_id, title="T", status="reviewing-implementation")
    insert_qa_requirement(
        conn, id=req_id, item_id=item_id, qa_kind=qa_kind,
        qa_phase="verification", blocking_mode="blocking",
        success_policy='{"base_url": "http://localhost:9", "steps": []}',
    )
    conn.commit()


class TestQaBrowserContextGet(unittest.TestCase):
    def test_rejects_missing_target(self):
        outcome = qa_browser.handle_qa_browser_context_get(
            _request("qa.browser_context.get", TargetRef(kind="global"),
                     payload={"project": "yoke"}),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_rejects_missing_project(self):
        outcome = qa_browser.handle_qa_browser_context_get(
            _request("qa.browser_context.get",
                     TargetRef(kind="item", item_id=42), payload={}),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_returns_browser_requirements_and_item_id(self):
        with test_database() as conn:
            _seed_browser_requirement(conn)
            insert_qa_requirement(
                conn, id=11, item_id=42, qa_kind="ac_verification",
                qa_phase="verification", blocking_mode="blocking",
                success_policy="",
            )
            conn.commit()
            outcome = qa_browser.handle_qa_browser_context_get(
                _request("qa.browser_context.get",
                         TargetRef(kind="item", item_id=42),
                         payload={"project": "yoke"}),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        result = outcome.result_payload
        self.assertEqual(result["item_id"], 42)
        self.assertEqual([r["id"] for r in result["requirements"]], [10])
        self.assertEqual(result["requirements"][0]["qa_kind"], "browser_smoke")
        self.assertFalse(result["deployment_recorded"])
        self.assertIsNone(result["deployed_sha"])

    def test_freshness_branch_returns_deployed_sha(self):
        with test_database() as conn:
            _seed_browser_requirement(conn)
            conn.execute(
                "INSERT INTO ephemeral_environments "
                "(project_id, branch, deployed_sha, status, created_at) "
                "VALUES (1, %s, %s, 'healthy', %s)",
                ("feature-x", "abc123", "2026-01-01T00:00:00Z"),
            )
            conn.commit()
            outcome = qa_browser.handle_qa_browser_context_get(
                _request("qa.browser_context.get",
                         TargetRef(kind="item", item_id=42),
                         payload={"project": "yoke",
                                  "expected_branch": "feature-x"}),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        result = outcome.result_payload
        self.assertTrue(result["deployment_recorded"])
        self.assertEqual(result["deployed_sha"], "abc123")
        self.assertIsNone(result["ephemeral_url"])

    def test_freshness_branch_returns_recorded_ephemeral_url(self):
        # The gate-entry URL read that used to be raw client SQL in the
        # advance skill: non-empty url comes back
        # alongside the freshness sha.
        with test_database() as conn:
            _seed_browser_requirement(conn)
            conn.execute(
                "INSERT INTO ephemeral_environments "
                "(project_id, branch, deployed_sha, url, status, created_at) "
                "VALUES (1, %s, %s, %s, 'healthy', %s)",
                ("feature-x", "abc123",
                 "https://feature-x.preview.example.com",
                 "2026-01-01T00:00:00Z"),
            )
            conn.commit()
            outcome = qa_browser.handle_qa_browser_context_get(
                _request("qa.browser_context.get",
                         TargetRef(kind="item", item_id=42),
                         payload={"project": "yoke",
                                  "expected_branch": "feature-x"}),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        result = outcome.result_payload
        self.assertEqual(result["deployed_sha"], "abc123")
        self.assertEqual(
            result["ephemeral_url"], "https://feature-x.preview.example.com",
        )

    def test_empty_string_url_reads_as_no_ephemeral_url(self):
        # Provisioned-but-undeployed rows carry url='' — the gate must
        # treat that as "no URL recorded", never hand it to the browser.
        with test_database() as conn:
            _seed_browser_requirement(conn)
            conn.execute(
                "INSERT INTO ephemeral_environments "
                "(project_id, branch, deployed_sha, url, status, created_at) "
                "VALUES (1, %s, %s, %s, 'pending', %s)",
                ("feature-x", "abc123", "", "2026-01-01T00:00:00Z"),
            )
            conn.commit()
            outcome = qa_browser.handle_qa_browser_context_get(
                _request("qa.browser_context.get",
                         TargetRef(kind="item", item_id=42),
                         payload={"project": "yoke",
                                  "expected_branch": "feature-x"}),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        self.assertIsNone(outcome.result_payload["ephemeral_url"])


class TestQaRunAdd(unittest.TestCase):
    def test_rejects_missing_target(self):
        outcome = qa_browser_writes.handle_qa_run_add(
            _request("qa.run.add", TargetRef(kind="global"),
                     payload={"executor_type": "browser_substrate"}),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_rejects_agent_for_browser_kind(self):
        with test_database() as conn:
            _seed_browser_requirement(conn)
            outcome = qa_browser_writes.handle_qa_run_add(
                _request("qa.run.add",
                         TargetRef(kind="qa_requirement", qa_requirement_id=10),
                         payload={"executor_type": "agent"}),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "policy_violation")

    def test_rejects_qa_kind_mismatch(self):
        with test_database() as conn:
            _seed_browser_requirement(conn)
            outcome = qa_browser_writes.handle_qa_run_add(
                _request("qa.run.add",
                         TargetRef(kind="qa_requirement", qa_requirement_id=10),
                         payload={"executor_type": "browser_substrate",
                                  "qa_kind": "browser_diff"}),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_started_run_inserts_with_null_verdict(self):
        with test_database() as conn:
            _seed_browser_requirement(conn)
            with patch(
                "yoke_core.domain.qa_events.emit_qa_run_event",
            ) as emit:
                outcome = qa_browser_writes.handle_qa_run_add(
                    _request(
                        "qa.run.add",
                        TargetRef(kind="qa_requirement", qa_requirement_id=10),
                        payload={"executor_type": "browser_substrate",
                                 "qa_kind": "browser_smoke",
                                 "raw_result": "{}"},
                    ),
                )
            self.assertTrue(outcome.primary_success, outcome.error)
            run_id = outcome.result_payload["qa_run_id"]
            row = conn.execute(
                "SELECT executor_type, qa_kind, verdict, completed_at "
                "FROM qa_runs WHERE id = %s",
                (run_id,),
            ).fetchone()
        self.assertEqual(row[0], "browser_substrate")
        self.assertEqual(row[1], "browser_smoke")
        self.assertIsNone(row[2])
        self.assertIsNone(row[3])
        self.assertEqual(
            emit.call_args.kwargs["event_name"], "QARunStarted",
        )


class TestQaRunComplete(unittest.TestCase):
    def _add_started_run(self, conn) -> int:
        with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
            outcome = qa_browser_writes.handle_qa_run_add(
                _request(
                    "qa.run.add",
                    TargetRef(kind="qa_requirement", qa_requirement_id=10),
                    payload={"executor_type": "browser_substrate"},
                ),
            )
        return int(outcome.result_payload["qa_run_id"])

    def test_rejects_missing_verdict_and_status(self):
        outcome = qa_browser_writes.handle_qa_run_complete(
            _request("qa.run.complete",
                     TargetRef(kind="qa_requirement", qa_requirement_id=10),
                     payload={"run_id": 1}),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_rejects_run_of_other_requirement(self):
        with test_database() as conn:
            _seed_browser_requirement(conn)
            insert_qa_requirement(
                conn, id=11, item_id=42, qa_kind="browser_diff",
                qa_phase="verification", blocking_mode="blocking",
                success_policy="",
            )
            conn.commit()
            run_id = self._add_started_run(conn)
            outcome = qa_browser_writes.handle_qa_run_complete(
                _request("qa.run.complete",
                         TargetRef(kind="qa_requirement", qa_requirement_id=11),
                         payload={"run_id": run_id,
                                  "execution_status": "captured"}),
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
                        payload={"run_id": run_id,
                                 "execution_status": "captured",
                                 "raw_result": '{"ok": true}'},
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
        self.assertEqual(
            emit.call_args.kwargs["event_name"], "QARunCaptured",
        )


if __name__ == "__main__":
    unittest.main()
