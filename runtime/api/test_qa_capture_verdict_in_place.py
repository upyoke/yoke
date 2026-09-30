"""A browser review resolves its capture rather than shadowing it.

The capture carries the commit its screenshots were taken against; an agent
review row carries none. Recording the review as a second run made that
identity-less row the requirement's latest, so the terminal gate read the
requirement as passing with no tree behind it and refused the merge as
stale-sha. These tests drive the real ``qa.run.record_verdict`` handler and
the real release gate.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from yoke_core.domain.handlers import qa_run
from yoke_core.domain.qa_merging_identity import recorded_head_sha

from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_agent_reviewed_capture_test_support import (
    browser_evidence_gate as _gate,
    capture as _capture,
    request as _request,
    seed_case as _seed_case,
)


CANDIDATE_SHA = "b" * 40


def _bind_capture_identity(conn, run_id: int) -> None:
    """Record the commit a browser capture's evidence was taken against."""
    conn.execute(
        "UPDATE qa_runs SET raw_result=%s WHERE id=%s",
        (
            json.dumps(
                {"code_identity": {"branch": "candidate", "sha": CANDIDATE_SHA}}
            ),
            run_id,
        ),
    )
    conn.commit()


def _latest_run(conn, requirement_id: int):
    return conn.execute(
        "SELECT id, performed_by, verdict, raw_result FROM qa_runs "
        "WHERE qa_requirement_id=%s ORDER BY id DESC LIMIT 1",
        (requirement_id,),
    ).fetchone()


def _record_agent_verdict(conn, requirement_id: int, payload: dict):
    """Drive the real handler, which resolves its own connection.

    ``test_database`` repoints the DSN at this same database, so the handler
    opening and closing its own connection is the production shape rather
    than a patched stand-in.
    """
    conn.commit()
    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        return qa_run.handle_qa_run_record_verdict(
            _request("qa.run.record_verdict", requirement_id, payload)
        )


class TestVerdictResolvesThePendingCapture(unittest.TestCase):
    """A review must not shadow the run that names the verified candidate.

    The capture carries the commit its screenshots were taken against; an
    agent review row carries none. Recording the review as a second run made
    that identity-less row the requirement's latest, and the terminal gate
    read the requirement as passing with no tree behind it.
    """

    def _reviewed_capture(self, conn, requirement_id: int):
        _seed_case(
            conn,
            requirement_id=requirement_id,
            method_id="browser-inspection",
            verdict_path="agent",
        )
        capture_run_id = _capture(conn, requirement_id)
        _bind_capture_identity(conn, capture_run_id)
        outcome = _record_agent_verdict(
            conn,
            requirement_id,
            {
                "performed_by": "agent",
                "verdict": "pass",
                "verdict_reason": "the screenshots show the new empty state",
            },
        )
        self.assertTrue(outcome.primary_success, outcome.error)
        return capture_run_id, outcome

    def test_no_second_run_is_opened(self):
        with test_database() as conn:
            capture_run_id, outcome = self._reviewed_capture(conn, 8411)

            runs = conn.execute(
                "SELECT COUNT(*) AS n FROM qa_runs WHERE qa_requirement_id=%s",
                (8411,),
            ).fetchone()["n"]

            self.assertEqual(runs, 1)
            self.assertEqual(
                int(outcome.result_payload["qa_run_id"]), capture_run_id
            )

    def test_the_latest_run_still_names_the_verified_candidate(self):
        with test_database() as conn:
            capture_run_id, _ = self._reviewed_capture(conn, 8412)

            latest = _latest_run(conn, 8412)

            self.assertEqual(int(latest["id"]), capture_run_id)
            self.assertEqual(latest["performed_by"], "browser_substrate")
            self.assertEqual(latest["verdict"], "pass")
            self.assertEqual(
                recorded_head_sha(latest["raw_result"]), CANDIDATE_SHA
            )

    def test_the_release_gate_accepts_the_capture_its_review_settled(self):
        with test_database() as conn:
            self._reviewed_capture(conn, 8413)

            self.assertIsNone(_gate(conn))

    def test_a_supplied_raw_result_is_refused_rather_than_overwriting(self):
        with test_database() as conn:
            _seed_case(
                conn,
                requirement_id=8414,
                method_id="browser-inspection",
                verdict_path="agent",
            )
            capture_run_id = _capture(conn, 8414)
            _bind_capture_identity(conn, capture_run_id)

            outcome = _record_agent_verdict(
                conn,
                8414,
                {
                    "performed_by": "agent",
                    "verdict": "pass",
                    "verdict_reason": "looks right",
                    "raw_result": json.dumps({"code_identity": {"sha": "c" * 40}}),
                },
            )

            self.assertFalse(outcome.primary_success)
            self.assertIn("already names the commit", outcome.error.message)
            self.assertEqual(
                recorded_head_sha(_latest_run(conn, 8414)["raw_result"]),
                CANDIDATE_SHA,
            )
