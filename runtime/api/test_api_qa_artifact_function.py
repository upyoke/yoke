"""Unit tests for ``qa.artifact.add`` — the artifact-handle DB leg.

Sibling of ``test_api_qa_browser_function.py`` (350-cap split). Handlers
run against the isolated Postgres fixture; the typed-handle contract is
the artifact-handle hard cutover: ``artifact_handle`` is the only file reference and
bare-path payloads are refused.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from yoke_core.domain.handlers import qa_browser_writes
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


class TestQaArtifactAdd(unittest.TestCase):
    def test_rejects_unknown_run(self):
        with test_database() as conn:
            _seed_browser_requirement(conn)
            outcome = qa_browser_writes.handle_qa_artifact_add(
                _request("qa.artifact.add",
                         TargetRef(kind="qa_requirement", qa_requirement_id=10),
                         payload={"run_id": 9999,
                                  "artifact_type": "screenshot",
                                  "artifact_handle": {
                                      "backend": "local",
                                      "path": "/tmp/home.png",
                                  }}),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "not_found")

    def test_rejects_bare_path_payloads(self):
        """Typed denial: bare-path shapes never silently become handles."""
        with test_database() as conn:
            _seed_browser_requirement(conn)
            for payload in (
                # retired column shape
                {"run_id": 1, "artifact_type": "screenshot",
                 "storage_path": "qa-artifacts/p/42/1/home.png"},
                # bare path where the handle belongs
                {"run_id": 1, "artifact_type": "screenshot",
                 "artifact_handle": "qa-artifacts/p/42/1/home.png"},
                # handle without backend
                {"run_id": 1, "artifact_type": "screenshot",
                 "artifact_handle": {"path": "/tmp/home.png"}},
                # missing handle entirely
                {"run_id": 1, "artifact_type": "screenshot"},
            ):
                outcome = qa_browser_writes.handle_qa_artifact_add(
                    _request(
                        "qa.artifact.add",
                        TargetRef(kind="qa_requirement", qa_requirement_id=10),
                        payload=payload,
                    ),
                )
                self.assertFalse(outcome.primary_success)
                self.assertEqual(outcome.error.code, "payload_invalid")
                self.assertIn("backend", outcome.error.message)

    def test_inserts_artifact_row(self):
        with test_database() as conn:
            _seed_browser_requirement(conn)
            with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
                run_outcome = qa_browser_writes.handle_qa_run_add(
                    _request(
                        "qa.run.add",
                        TargetRef(kind="qa_requirement", qa_requirement_id=10),
                        payload={"executor_type": "browser_substrate"},
                    ),
                )
            run_id = int(run_outcome.result_payload["qa_run_id"])
            outcome = qa_browser_writes.handle_qa_artifact_add(
                _request(
                    "qa.artifact.add",
                    TargetRef(kind="qa_requirement", qa_requirement_id=10),
                    payload={
                        "run_id": run_id,
                        "artifact_type": "screenshot",
                        "content_type": "image/png",
                        "artifact_handle": {
                            "backend": "s3",
                            "bucket": "p-prod-artifacts",
                            "key": "qa-artifacts/p/42/1/home.png",
                        },
                        "metadata": "{}",
                    },
                ),
            )
            self.assertTrue(outcome.primary_success, outcome.error)
            artifact_id = outcome.result_payload["qa_artifact_id"]
            row = conn.execute(
                "SELECT qa_run_id, artifact_type, content_type, artifact_handle "
                "FROM qa_artifacts WHERE id = %s",
                (artifact_id,),
            ).fetchone()
        self.assertEqual(row[0], run_id)
        self.assertEqual(row[1], "screenshot")
        self.assertEqual(row[2], "image/png")
        self.assertEqual(
            json.loads(row[3]),
            {
                "backend": "s3",
                "bucket": "p-prod-artifacts",
                "key": "qa-artifacts/p/42/1/home.png",
            },
        )


if __name__ == "__main__":
    unittest.main()
