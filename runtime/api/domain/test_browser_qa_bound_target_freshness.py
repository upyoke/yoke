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

from yoke_core.domain.browser_qa_case_target import (
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


def _execution(
    conn,
    *,
    execution_id: str,
    item_id: int,
    roster_requirement_ids: list[int],
    target: dict | str | None,
    transition_id: str = "implemented",
):
    """Record one live execution whose roster names the given cases."""
    conn.execute(
        "INSERT INTO qa_plan_executions (id, item_id, transition_id, actor_id, "
        "session_id, state, roster_json, roster_digest, cursor_ordinal, "
        "created_at, heartbeat_at, execution_target_json) VALUES "
        "(%s, %s, %s, 'op', 's-1', 'active', %s, 'd', 0, %s, %s, %s)",
        (
            execution_id,
            item_id,
            transition_id,
            json.dumps([{"requirement_id": r} for r in roster_requirement_ids]),
            NOW,
            NOW,
            (target if isinstance(target, str) else json.dumps(target))
            if target is not None
            else None,
        ),
    )
    conn.commit()


class TestBoundTargetMembership(unittest.TestCase):
    def test_a_case_takes_its_own_execution_target_not_a_sibling_one(self):
        with test_database() as conn:
            # One item, two plans running at once, each frozen against a
            # different environment. Sharing a subject must lend neither
            # case the other's target.
            _seed_case(conn, requirement_id=9501, target=None)
            insert_qa_requirement(
                conn,
                id=9502,
                item_id=ITEM_ID,
                qa_kind="method_case",
                method_id="browser-inspection",
            )
            conn.commit()
            mine = _target(app_url="https://mine.example.test")
            sibling = _target(app_url="https://sibling.example.test")
            _execution(
                conn,
                execution_id="11111111-1111-1111-1111-111111111111",
                item_id=ITEM_ID,
                roster_requirement_ids=[9501],
                target=mine,
            )
            # A second plan on the same item, at its own transition, newer -
            # so it would win any latest-subject-execution selection.
            _execution(
                conn,
                execution_id="22222222-2222-2222-2222-222222222222",
                item_id=ITEM_ID,
                roster_requirement_ids=[9502],
                target=sibling,
                transition_id="reviewing-implementation",
            )

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9501, project_id=1
            )

            assert bound is not None
            self.assertEqual(bound.origin, "https://mine.example.test")

    def test_the_execution_snapshot_outranks_a_rematerialized_row(self):
        with test_database() as conn:
            # The row was rematerialized onto a new environment while the
            # execution that froze the old one is still in flight.
            _seed_case(
                conn,
                requirement_id=9503,
                target=_target(app_url="https://rematerialized.example.test"),
            )
            _execution(
                conn,
                execution_id="33333333-3333-3333-3333-333333333333",
                item_id=ITEM_ID,
                roster_requirement_ids=[9503],
                target=_target(app_url="https://frozen.example.test"),
            )

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9503, project_id=1
            )

            assert bound is not None
            self.assertEqual(bound.origin, "https://frozen.example.test")

    def test_a_case_in_no_roster_falls_back_to_its_own_recorded_target(self):
        with test_database() as conn:
            _seed_case(
                conn,
                requirement_id=9504,
                target=_target(app_url="https://recorded.example.test"),
            )
            _execution(
                conn,
                execution_id="44444444-4444-4444-4444-444444444444",
                item_id=ITEM_ID,
                roster_requirement_ids=[9599],
                target=_target(app_url="https://someone-elses.example.test"),
            )

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9504, project_id=1
            )

            assert bound is not None
            self.assertEqual(bound.origin, "https://recorded.example.test")

    def test_a_malformed_bound_target_fails_closed(self):
        with test_database() as conn:
            _seed_case(conn, requirement_id=9505, target=None)
            _execution(
                conn,
                execution_id="55555555-5555-5555-5555-555555555555",
                item_id=ITEM_ID,
                roster_requirement_ids=[9505],
                target="{not json",
            )

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9505, project_id=1
            )

            # A target that exists and cannot be read must refuse, never
            # quietly become a branch-preview question.
            assert bound is not None
            self.assertIn("not readable JSON", bound.unresolved)

            failure, origin = _establish_deployment_freshness(
                "yoke",
                "main",
                SERVED_SHA,
                context={"deployment_target": bound.as_payload()},
                fetch_identity=_serves(SERVED_SHA),
            )
            self.assertIsNotNone(failure)
            self.assertEqual(origin, "")

    def test_a_bound_target_naming_no_endpoints_fails_closed(self):
        with test_database() as conn:
            _seed_case(conn, requirement_id=9506, target={"schema": 2})
            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9506, project_id=1
            )
            assert bound is not None
            self.assertIn("no environment and endpoints", bound.unresolved)
