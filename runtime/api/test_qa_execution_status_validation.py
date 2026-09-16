"""``execution_status`` is refused by name before it reaches the database."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_cli.commands.adapters import qa_browser as qa_browser_cli
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.qa_execution_status import VALID_EXECUTION_STATUSES
from yoke_core.domain.handlers import qa_browser_writes

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database


REQUIREMENT_ID = 10
ITEM_ID = 42


def _request(function_id: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=REQUIREMENT_ID),
        payload=payload,
    )


def _seed_requirement(conn) -> None:
    insert_item(conn, id=ITEM_ID, title="T", status="reviewing-implementation")
    insert_qa_requirement(
        conn,
        id=REQUIREMENT_ID,
        item_id=ITEM_ID,
        qa_kind="plan_case",
        qa_phase="verification",
        blocking_mode="blocking",
        success_policy="",
    )
    conn.commit()


def _add_started_run(conn) -> int:
    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        outcome = qa_browser_writes.handle_qa_run_add(
            _request("qa.run.add", {"performed_by": "browser_substrate"}),
        )
    assert outcome.primary_success, outcome.error
    return int(outcome.result_payload["qa_run_id"])


class TestRunCompleteExecutionStatus(unittest.TestCase):
    def test_unsupported_status_is_refused_and_lists_supported_values(self):
        with test_database() as conn:
            _seed_requirement(conn)
            run_id = _add_started_run(conn)
            outcome = qa_browser_writes.handle_qa_run_complete(
                _request(
                    "qa.run.complete",
                    {"run_id": run_id, "execution_status": "completed"},
                ),
            )
            self.assertFalse(outcome.primary_success)
            self.assertEqual(outcome.error.code, "payload_invalid")
            self.assertEqual(outcome.error.jsonpath, "$.payload.execution_status")
            message = str(outcome.error.message)
            self.assertIn("execution_status", message)
            for supported in VALID_EXECUTION_STATUSES:
                self.assertIn(supported, message)

    def test_refused_status_leaves_the_run_unchanged(self):
        with test_database() as conn:
            _seed_requirement(conn)
            run_id = _add_started_run(conn)
            before = conn.execute(
                "SELECT execution_status, verdict, completed_at FROM qa_runs "
                "WHERE id = %s",
                (run_id,),
            ).fetchone()
            outcome = qa_browser_writes.handle_qa_run_complete(
                _request(
                    "qa.run.complete",
                    {
                        "run_id": run_id,
                        "verdict": "pass",
                        "execution_status": "completed",
                    },
                ),
            )
            self.assertFalse(outcome.primary_success)
            after = conn.execute(
                "SELECT execution_status, verdict, completed_at FROM qa_runs "
                "WHERE id = %s",
                (run_id,),
            ).fetchone()
        self.assertEqual(tuple(after), tuple(before))

    def test_supported_statuses_still_persist(self):
        for supported in VALID_EXECUTION_STATUSES:
            with self.subTest(execution_status=supported):
                with test_database() as conn:
                    _seed_requirement(conn)
                    run_id = _add_started_run(conn)
                    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
                        outcome = qa_browser_writes.handle_qa_run_complete(
                            _request(
                                "qa.run.complete",
                                {
                                    "run_id": run_id,
                                    "execution_status": supported,
                                },
                            ),
                        )
                    self.assertTrue(outcome.primary_success, outcome.error)
                    stored = conn.execute(
                        "SELECT execution_status FROM qa_runs WHERE id = %s",
                        (run_id,),
                    ).fetchone()
                self.assertEqual(stored[0], supported)

    def test_omitted_status_keeps_verdict_only_completion(self):
        with test_database() as conn:
            _seed_requirement(conn)
            run_id = _add_started_run(conn)
            with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
                outcome = qa_browser_writes.handle_qa_run_complete(
                    _request("qa.run.complete", {"run_id": run_id, "verdict": "pass"}),
                )
            self.assertTrue(outcome.primary_success, outcome.error)
            stored = conn.execute(
                "SELECT execution_status, verdict FROM qa_runs WHERE id = %s",
                (run_id,),
            ).fetchone()
        self.assertIsNone(stored[0])
        self.assertEqual(stored[1], "pass")


class TestRunAddExecutionStatus(unittest.TestCase):
    def test_unsupported_status_is_refused_before_insert(self):
        with test_database() as conn:
            _seed_requirement(conn)
            outcome = qa_browser_writes.handle_qa_run_add(
                _request(
                    "qa.run.add",
                    {
                        "performed_by": "browser_substrate",
                        "execution_status": "completed",
                    },
                ),
            )
            self.assertFalse(outcome.primary_success)
            self.assertEqual(outcome.error.code, "payload_invalid")
            self.assertEqual(outcome.error.jsonpath, "$.payload.execution_status")
            remaining = conn.execute(
                "SELECT count(*) FROM qa_runs WHERE qa_requirement_id = %s",
                (REQUIREMENT_ID,),
            ).fetchone()
        self.assertEqual(remaining[0], 0)


class TestExecutionStatusCliContract(unittest.TestCase):
    def test_usage_lines_name_every_supported_value(self):
        for usage in (
            qa_browser_cli.QA_RUN_ADD_USAGE,
            qa_browser_cli.QA_RUN_COMPLETE_USAGE,
        ):
            for supported in VALID_EXECUTION_STATUSES:
                self.assertIn(supported, usage)

    def test_cli_refuses_an_unsupported_status_without_dispatching(self):
        cases = (
            (
                qa_browser_cli.qa_run_add,
                ["--performed-by", "browser_substrate"],
            ),
            (qa_browser_cli.qa_run_complete, ["--run-id", "1"]),
        )
        for entrypoint, extra_args in cases:
            with self.subTest(entrypoint=entrypoint.__name__):
                args = [
                    "--requirement-id",
                    str(REQUIREMENT_ID),
                    *extra_args,
                    "--execution-status",
                    "completed",
                ]
                with patch.object(qa_browser_cli, "dispatch_and_emit") as dispatch:
                    exit_code = entrypoint(args)
                self.assertEqual(exit_code, 2)
                dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
