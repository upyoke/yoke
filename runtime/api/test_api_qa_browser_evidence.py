"""Unit tests for qa.screenshot_evidence.{pending_count,satisfy}.

The advance browser-QA gate's evidence legs, against the isolated
Postgres fixture. Family overview:
``runtime/api/test_api_qa_browser_function.py``.
"""

from __future__ import annotations

import unittest

from yoke_core.domain.handlers import qa_browser_evidence
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database


def _request(function_id: str, item_id: int, payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload or {},
    )


def _seed_evidence_fixture(conn, *, item_id: int = 42) -> None:
    """One browser requirement + one ac_verification row needing evidence."""
    insert_item(conn, id=item_id, title="T", status="reviewing-implementation")
    insert_qa_requirement(
        conn, id=10, item_id=item_id, qa_kind="browser_smoke",
        qa_phase="verification", blocking_mode="blocking",
        success_policy='{"base_url": "http://localhost:9", "steps": []}',
    )
    insert_qa_requirement(
        conn, id=11, item_id=item_id, qa_kind="ac_verification",
        qa_phase="verification", blocking_mode="blocking",
        success_policy="AC must show [requires_screenshot_evidence]",
    )
    conn.commit()


def _insert_capture_run(conn, *, verdict, execution_status="captured") -> None:
    conn.execute(
        "INSERT INTO qa_runs (qa_requirement_id, executor_type, qa_kind, "
        "verdict, execution_status, created_at) "
        "VALUES (10, 'browser_substrate', 'browser_smoke', %s, %s, %s)",
        (verdict, execution_status, "2026-01-01T00:00:00Z"),
    )
    conn.commit()


class TestPendingCount(unittest.TestCase):
    def test_rejects_missing_target(self):
        outcome = qa_browser_evidence.handle_qa_screenshot_evidence_pending_count(
            FunctionCallRequest(
                function="qa.screenshot_evidence.pending_count",
                actor=ActorContext(actor_id="op", session_id="s-1"),
                target=TargetRef(kind="global"),
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_counts_unsatisfied_requirements(self):
        with test_database() as conn:
            _seed_evidence_fixture(conn)
            outcome = qa_browser_evidence.handle_qa_screenshot_evidence_pending_count(
                _request("qa.screenshot_evidence.pending_count", 42),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        self.assertEqual(outcome.result_payload["pending_count"], 1)
        self.assertEqual(outcome.result_payload["item_id"], 42)

    def test_zero_when_no_evidence_requirements(self):
        with test_database() as conn:
            insert_item(conn, id=42, title="T", status="reviewing-implementation")
            conn.commit()
            outcome = qa_browser_evidence.handle_qa_screenshot_evidence_pending_count(
                _request("qa.screenshot_evidence.pending_count", 42),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        self.assertEqual(outcome.result_payload["pending_count"], 0)


class TestSatisfy(unittest.TestCase):
    def test_refuses_without_inspection_verified_capture(self):
        with test_database() as conn:
            _seed_evidence_fixture(conn)
            # A capture that was never inspection-verified (verdict NULL).
            _insert_capture_run(conn, verdict=None)
            outcome = qa_browser_evidence.handle_qa_screenshot_evidence_satisfy(
                _request("qa.screenshot_evidence.satisfy", 42),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "capture_not_verified")
        self.assertIn("qa.run.complete", outcome.error.message)

    def test_bridges_verified_capture_to_ac_pass(self):
        with test_database() as conn:
            _seed_evidence_fixture(conn)
            _insert_capture_run(conn, verdict="pass")
            outcome = qa_browser_evidence.handle_qa_screenshot_evidence_satisfy(
                _request(
                    "qa.screenshot_evidence.satisfy", 42,
                    payload={"evidence": "looks right"},
                ),
            )
            self.assertTrue(outcome.primary_success, outcome.error)
            self.assertEqual(outcome.result_payload["satisfied_count"], 1)
            row = conn.execute(
                "SELECT verdict, raw_result FROM qa_runs "
                "WHERE qa_requirement_id = 11",
            ).fetchone()
        self.assertEqual(row[0], "pass")
        self.assertEqual(row[1], "looks right")

    def test_noop_when_nothing_pending(self):
        with test_database() as conn:
            insert_item(conn, id=42, title="T", status="reviewing-implementation")
            insert_qa_requirement(
                conn, id=10, item_id=42, qa_kind="browser_smoke",
                qa_phase="verification", blocking_mode="blocking",
                success_policy="",
            )
            conn.commit()
            _insert_capture_run(conn, verdict="pass")
            outcome = qa_browser_evidence.handle_qa_screenshot_evidence_satisfy(
                _request("qa.screenshot_evidence.satisfy", 42),
            )
        self.assertTrue(outcome.primary_success, outcome.error)
        self.assertEqual(outcome.result_payload["satisfied_count"], 0)


if __name__ == "__main__":
    unittest.main()
