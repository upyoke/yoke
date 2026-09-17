"""A Browser case verifies the deployment it is bound to, not a branch.

Freshness used to choose its subject by attachment: a deployment-run case
asked the environment that run targeted, and everything else asked the
branch's preview. Once a case could name an environment of its own, that
made an item case bound to production probe a preview host nothing ever
deployed — so a case explicitly aimed at production could not prove what it
browsed, and its evidence was refused as recording no exact revision.

The bound target now answers first. What it does NOT change is the proof:
the same identity probe, against the same configured served-revision path,
and a case bound to nothing still asks the branch.
"""

from __future__ import annotations

import json
import unittest

from yoke_core.domain.browser_qa_deployment_identity import (
    resolve_case_deployment_under_test,
)
from yoke_core.domain.browser_qa_freshness import _establish_deployment_freshness
from yoke_core.domain.served_revision_probe import ServedRevisionRead

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database

ITEM_ID = 9301
SERVED_SHA = "1111111111111111111111111111111111111111"
OTHER_SHA = "2222222222222222222222222222222222222222"
PROD_ORIGIN = "https://app.example.test"
IDENTITY_PATH = "/candidate-revision"
NOW = "2026-09-17T00:00:00Z"


def _target(project_id: int = 1, app_url: str = PROD_ORIGIN) -> dict:
    return {
        "schema": 2,
        "environment": {"name": "prod"},
        "project": {"id": project_id, "slug": "yoke", "name": "Yoke"},
        "endpoints": {"app_url": app_url, "api_url": app_url},
    }


def _seed_case(conn, *, requirement_id: int, target: dict | None) -> int:
    insert_item(conn, id=ITEM_ID, title="Bound to production")
    insert_qa_requirement(
        conn,
        id=requirement_id,
        item_id=ITEM_ID,
        qa_kind="method_case",
        method_id="browser-inspection",
        execution_target_json=(json.dumps(target) if target else None),
    )
    conn.commit()
    return requirement_id


def _configure_identity(conn, *, project_id: int = 1, path: str = IDENTITY_PATH):
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings, created_at) "
        "VALUES (%s, 'health-endpoint', %s, %s)",
        (project_id, json.dumps({"identity_path": path}), NOW),
    )
    conn.commit()


def _serves(sha: str):
    """Answer the served-revision probe the way a live deployment would."""
    return lambda url: ServedRevisionRead(status=200, body=sha)


class TestBoundTargetFreshness(unittest.TestCase):
    def test_bound_production_target_is_verified_at_its_own_origin(self):
        with test_database() as conn:
            _seed_case(conn, requirement_id=9401, target=_target())
            _configure_identity(conn)

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9401, project_id=1
            )
            assert bound is not None
            self.assertEqual(bound.origin, PROD_ORIGIN)
            self.assertEqual(bound.identity_path, IDENTITY_PATH)

            failure, origin = _establish_deployment_freshness(
                "yoke",
                "main",
                SERVED_SHA,
                context={"deployment_target": bound.as_payload()},
                fetch_identity=_serves(SERVED_SHA),
            )

            self.assertIsNone(failure)
            # The origin the evidence may be collected from is the bound
            # target's own, never a host derived from the branch name.
            self.assertEqual(origin, PROD_ORIGIN)

    def test_a_target_serving_another_revision_is_refused(self):
        with test_database() as conn:
            _seed_case(conn, requirement_id=9402, target=_target())
            _configure_identity(conn)
            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9402, project_id=1
            )

            failure, origin = _establish_deployment_freshness(
                "yoke",
                "main",
                SERVED_SHA,
                context={"deployment_target": bound.as_payload()},
                fetch_identity=_serves(OTHER_SHA),
            )

            self.assertIsNotNone(failure)
            self.assertEqual(origin, "")

    def test_a_project_publishing_no_identity_proof_is_refused(self):
        with test_database() as conn:
            _seed_case(conn, requirement_id=9403, target=_target())

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9403, project_id=1
            )
            assert bound is not None
            self.assertEqual(bound.identity_path, "")

            failure, origin = _establish_deployment_freshness(
                "yoke",
                "main",
                SERVED_SHA,
                context={"deployment_target": bound.as_payload()},
                fetch_identity=_serves(SERVED_SHA),
            )

            # Unconfigured proof fails closed: nothing read the deployment
            # back, so nothing may claim it was serving this revision.
            self.assertIsNotNone(failure)
            self.assertEqual(origin, "")

    def test_a_target_owned_by_another_project_is_refused(self):
        with test_database() as conn:
            _seed_case(conn, requirement_id=9404, target=_target(project_id=99))
            _configure_identity(conn)

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9404, project_id=1
            )

            assert bound is not None
            self.assertIn("another", bound.unresolved)
            failure, origin = _establish_deployment_freshness(
                "yoke",
                "main",
                SERVED_SHA,
                context={"deployment_target": bound.as_payload()},
                fetch_identity=_serves(SERVED_SHA),
            )
            self.assertIsNotNone(failure)
            self.assertEqual(origin, "")

    def test_a_case_bound_to_nothing_still_asks_the_branch_preview(self):
        with test_database() as conn:
            _seed_case(conn, requirement_id=9405, target=None)

            self.assertIsNone(
                resolve_case_deployment_under_test(
                    conn, requirement_id=9405, project_id=1
                )
            )

            # No bound target means no deployment_target in the context, so
            # the branch-preview path runs exactly as it always has.
            failure, origin = _establish_deployment_freshness(
                "yoke",
                "main",
                SERVED_SHA,
                context={"deployment_recorded": False},
                fetch_identity=_serves(SERVED_SHA),
            )

            self.assertIsNotNone(failure)
            self.assertEqual(origin, "")
