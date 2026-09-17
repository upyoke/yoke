"""A Browser case bound to a run preview asks the preview, not an environment.

A preview deployed for one run is never registered as an environment — there
is nothing standing to register — so resolving it by environment id answered
"this run targets no registered environment" and refused QA on a deployment
that had demonstrably been deployed. What located it is the receipt its own
deploying stage wrote, and that receipt is what these cover: it names WHERE
to ask, it must still belong to this run, stage, project and a ready preview,
and it never stands in for asking that url what it serves now.
"""

from __future__ import annotations

import json
import unittest

from yoke_core.domain.browser_qa_case_target import (
    resolve_case_deployment_under_test,
)
from yoke_core.domain.browser_qa_freshness import _establish_deployment_freshness
from yoke_core.domain.served_revision_probe import ServedRevisionRead

from runtime.api.fixtures.backlog_inserts import insert_deployment_run
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database

RUN_ID = "run-20260101-001"
OTHER_RUN_ID = "run-20260101-002"
SOURCE_STAGE = "release-preview"
PREVIEW_URL = "https://run-20260101-001.example.test"
PREVIEW_PATH = "/candidate-revision"
SERVED_SHA = "3333333333333333333333333333333333333333"
OTHER_SHA = "4444444444444444444444444444444444444444"
NOW = "2026-01-01T00:00:00Z"


def _preview_target(*, receipt_id: int, run_id: str = RUN_ID, project_id: int = 1):
    return {
        "schema": 4,
        "target_kind": "deployment",
        "environment": {"kind": "run_preview", "name": run_id},
        "deployment": {"run_id": run_id, "stage": "preview-qa"},
        "endpoints": {"api_url": PREVIEW_URL, "app_url": PREVIEW_URL},
        "observation": {"receipt_id": receipt_id, "source_stage": SOURCE_STAGE},
        "observed_url": PREVIEW_URL,
        "project": {"id": project_id, "slug": "yoke", "name": "Yoke"},
    }


def _insert_receipt(
    conn,
    *,
    receipt_id: int,
    run_id: str = RUN_ID,
    stage_name: str = SOURCE_STAGE,
    target_kind: str = "run_preview",
    status: str = "ready",
    observed_url: str = PREVIEW_URL,
) -> None:
    conn.execute(
        "INSERT INTO deployment_stage_receipts "
        "(id, run_id, stage_name, attempt_number, correlation_id, target_kind, "
        "target_name, status, observed_url, executor, created_at) "
        "VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s, 'github-actions-workflow', %s)",
        (
            receipt_id,
            run_id,
            stage_name,
            f"{run_id}:{stage_name}",
            target_kind,
            run_id,
            status,
            observed_url,
            NOW,
        ),
    )
    conn.commit()


def _configure_preview_identity(conn, *, project_id: int = 1) -> None:
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings, created_at) "
        "VALUES (%s, 'ephemeral-env', %s, %s)",
        (project_id, json.dumps({"identity_path": PREVIEW_PATH}), NOW),
    )
    conn.commit()


def _seed(conn, *, requirement_id: int, target: dict, run_id: str = RUN_ID) -> None:
    insert_deployment_run(conn, id=run_id, created_at=NOW)
    insert_qa_requirement(
        conn,
        id=requirement_id,
        item_id=None,
        deployment_run_id=run_id,
        qa_kind="method_case",
        method_id="browser-inspection",
        execution_target_json=json.dumps(target),
    )
    conn.commit()


def _serves(sha: str):
    return lambda url: ServedRevisionRead(status=200, body=sha)


class TestRunPreviewTarget(unittest.TestCase):
    def test_the_preview_is_reached_at_the_url_its_receipt_recorded(self):
        with test_database() as conn:
            _seed(conn, requirement_id=9501, target=_preview_target(receipt_id=701))
            _insert_receipt(conn, receipt_id=701)
            _configure_preview_identity(conn)

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9501, project_id=1
            )

            assert bound is not None
            self.assertEqual(bound.unresolved, "")
            self.assertEqual(bound.origin, PREVIEW_URL)
            # The preview's own capability answers, not the persistent one.
            self.assertEqual(bound.identity_path, PREVIEW_PATH)

    def test_the_recorded_url_is_still_asked_what_it_serves_now(self):
        with test_database() as conn:
            _seed(conn, requirement_id=9502, target=_preview_target(receipt_id=702))
            _insert_receipt(conn, receipt_id=702)
            _configure_preview_identity(conn)
            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9502, project_id=1
            )

            failure, origin, _sha = _establish_deployment_freshness(
                "yoke",
                "main",
                SERVED_SHA,
                context={"deployment_target": bound.as_payload()},
                fetch_identity=_serves(SERVED_SHA),
            )

            self.assertIsNone(failure)
            self.assertEqual(origin, PREVIEW_URL)

    def test_a_preview_serving_another_revision_is_refused(self):
        """The receipt locates the target; it never answers for it."""
        with test_database() as conn:
            _seed(conn, requirement_id=9503, target=_preview_target(receipt_id=703))
            _insert_receipt(conn, receipt_id=703)
            _configure_preview_identity(conn)
            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9503, project_id=1
            )

            failure, origin, _sha = _establish_deployment_freshness(
                "yoke",
                "main",
                SERVED_SHA,
                context={"deployment_target": bound.as_payload()},
                fetch_identity=_serves(OTHER_SHA),
            )

            self.assertIsNotNone(failure)
            self.assertEqual(origin, "")


class TestRunPreviewReceiptAuthority(unittest.TestCase):
    def test_a_receipt_that_was_never_recorded_refuses(self):
        with test_database() as conn:
            _seed(conn, requirement_id=9511, target=_preview_target(receipt_id=711))
            _configure_preview_identity(conn)

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9511, project_id=1
            )

            assert bound is not None
            self.assertIn("not recorded", bound.unresolved)
            self.assertEqual(bound.origin, "")

    def test_a_receipt_from_another_run_refuses(self):
        with test_database() as conn:
            _seed(conn, requirement_id=9512, target=_preview_target(receipt_id=712))
            insert_deployment_run(conn, id=OTHER_RUN_ID, created_at=NOW)
            _insert_receipt(conn, receipt_id=712, run_id=OTHER_RUN_ID)
            _configure_preview_identity(conn)

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9512, project_id=1
            )

            assert bound is not None
            self.assertIn(OTHER_RUN_ID, bound.unresolved)
            self.assertEqual(bound.origin, "")

    def test_a_receipt_from_another_stage_refuses(self):
        with test_database() as conn:
            _seed(conn, requirement_id=9513, target=_preview_target(receipt_id=713))
            _insert_receipt(conn, receipt_id=713, stage_name="some-other-stage")
            _configure_preview_identity(conn)

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9513, project_id=1
            )

            assert bound is not None
            self.assertIn("some-other-stage", bound.unresolved)

    def test_a_receipt_owned_by_another_project_refuses(self):
        with test_database() as conn:
            _seed(conn, requirement_id=9514, target=_preview_target(receipt_id=714))
            _insert_receipt(conn, receipt_id=714)
            _configure_preview_identity(conn)

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9514, project_id=2
            )

            assert bound is not None
            self.assertIn("another project", bound.unresolved)

    def test_a_preview_never_reported_deployed_refuses(self):
        with test_database() as conn:
            _seed(conn, requirement_id=9515, target=_preview_target(receipt_id=715))
            _insert_receipt(conn, receipt_id=715, status="pending")
            _configure_preview_identity(conn)

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9515, project_id=1
            )

            assert bound is not None
            self.assertIn("pending", bound.unresolved)

    def test_a_receipt_recording_a_different_url_refuses(self):
        with test_database() as conn:
            _seed(conn, requirement_id=9516, target=_preview_target(receipt_id=716))
            _insert_receipt(
                conn, receipt_id=716, observed_url="https://elsewhere.example.test"
            )
            _configure_preview_identity(conn)

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9516, project_id=1
            )

            assert bound is not None
            self.assertIn("ambiguous", bound.unresolved)

    def test_a_snapshot_naming_no_receipt_refuses(self):
        with test_database() as conn:
            target = _preview_target(receipt_id=717)
            target.pop("observation")
            _seed(conn, requirement_id=9517, target=target)
            _configure_preview_identity(conn)

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9517, project_id=1
            )

            assert bound is not None
            self.assertIn("no deploying stage receipt", bound.unresolved)


if __name__ == "__main__":
    unittest.main()
