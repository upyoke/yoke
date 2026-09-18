"""Persistent/post_deploy Browser cases ask the named environment, not a preview.

A standalone item case with ``target_env=prod`` and no frozen snapshot used
to omit ``deployment_target``, so freshness fell through to the branch
preview and raised SHA_MISMATCH against a host the case was never about.
The named environment, a run-attached row, and a run-member execution
snapshot now populate the existing deployment_target so
``validate_deployment_identity`` asks that host's identity path.
"""

from __future__ import annotations

import json
import unittest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.api_urls import HOSTED_PLATFORM_URL
from yoke_core.domain.browser_qa_case_target import (
    resolve_case_deployment_under_test,
)
from yoke_core.domain.browser_qa_freshness import _establish_deployment_freshness
from yoke_core.domain.browser_qa_freshness_outcome import (
    DEPLOYMENT_RECORD_MISSING,
    DEPLOYMENT_TARGET_UNRESOLVED,
    IDENTITY_PROOF_MALFORMED,
    IDENTITY_PROOF_UNAVAILABLE,
    SHA_MISMATCH,
)
from yoke_core.domain.handlers import qa_browser
from yoke_core.domain.served_revision_probe import ServedRevisionRead

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database

ITEM_ID = 9601
REQ_STANDALONE = 9611
REQ_MEMBER = 9612
REQ_RUN = 9613
REQ_UNBOUND = 9614
REQ_CROSS = 9615
REQ_MISSING = 9616
SERVED_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
OTHER_SHA = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
IDENTITY_PATH = "/api/orgs/upyoke/v1/health"
NOW = "2026-09-18T00:00:00Z"
RUN_ID = "run-20260918-001"


def _seed_prod(conn, *, path: str = IDENTITY_PATH, project_id: int = 1) -> None:
    conn.execute(
        "INSERT INTO environments (site, project_id, name, url, settings, created_at) "
        "VALUES (1, %s, 'prod', %s, %s, %s)",
        (
            project_id,
            HOSTED_PLATFORM_URL,
            json.dumps({"qa": {"identity_path": path}}) if path else "{}",
            NOW,
        ),
    )
    conn.commit()


def _seed_item_case(conn, *, requirement_id: int, target_env: str | None) -> None:
    insert_item(conn, id=ITEM_ID, title="Persistent production acceptance")
    insert_qa_requirement(
        conn,
        id=requirement_id,
        item_id=ITEM_ID,
        qa_kind="method_case",
        qa_phase="post_deploy",
        method_id="browser-inspection",
        target_env=target_env,
        method_config=json.dumps({"base_url": HOSTED_PLATFORM_URL}),
    )
    conn.commit()


def _context(requirement_id: int) -> dict:
    outcome = qa_browser.handle_qa_browser_context_get(
        FunctionCallRequest(
            function="qa.browser_context.get",
            actor=ActorContext(actor_id="op", session_id="s-persistent"),
            target=TargetRef(kind="item", item_id=ITEM_ID),
            payload={
                "project": "yoke",
                "requirement_id": requirement_id,
                "expected_branch": "main",
            },
        ),
    )
    assert outcome.primary_success, outcome.error
    return outcome.result_payload


def _asked(sha: str, *, status: int = 200, error: str = ""):
    urls: list[str] = []

    def fetch(url: str) -> ServedRevisionRead:
        urls.append(url)
        if error:
            return ServedRevisionRead(error=error)
        return ServedRevisionRead(status=status, body=sha)

    return fetch, urls


class TestStandalonePersistentTargetEnv(unittest.TestCase):
    def test_named_prod_without_a_snapshot_asks_the_environment_identity_path(self):
        with test_database() as conn:
            _seed_prod(conn)
            _seed_item_case(conn, requirement_id=REQ_STANDALONE, target_env="prod")

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=REQ_STANDALONE, project_id=1
            )
            assert bound is not None
            self.assertEqual(bound.environment, "prod")
            self.assertEqual(bound.origin, HOSTED_PLATFORM_URL)
            self.assertEqual(bound.identity_path, IDENTITY_PATH)

            context = _context(REQ_STANDALONE)
            self.assertEqual(context["deployment_target"]["environment"], "prod")
            self.assertFalse(context["deployment_recorded"])
            fetch, urls = _asked(SERVED_SHA)
            failure, origin, sha = _establish_deployment_freshness(
                "yoke",
                "main",
                SERVED_SHA,
                context=context,
                fetch_identity=fetch,
            )
            self.assertIsNone(failure)
            self.assertEqual(origin, HOSTED_PLATFORM_URL)
            self.assertEqual(sha, SERVED_SHA)
            self.assertEqual(urls, [f"{HOSTED_PLATFORM_URL}{IDENTITY_PATH}"])

    def test_a_wrong_revision_is_refused_without_asking_a_preview(self):
        with test_database() as conn:
            _seed_prod(conn)
            _seed_item_case(conn, requirement_id=REQ_STANDALONE, target_env="prod")
            fetch, urls = _asked(OTHER_SHA)
            failure, origin, _sha = _establish_deployment_freshness(
                "yoke",
                "main",
                SERVED_SHA,
                context=_context(REQ_STANDALONE),
                fetch_identity=fetch,
            )
            self.assertIsNotNone(failure)
            self.assertEqual(failure.reason, SHA_MISMATCH)
            self.assertEqual(origin, "")
            self.assertEqual(urls, [f"{HOSTED_PLATFORM_URL}{IDENTITY_PATH}"])

    def test_missing_identity_path_is_refused_by_name(self):
        with test_database() as conn:
            _seed_prod(conn, path="")
            _seed_item_case(conn, requirement_id=REQ_MISSING, target_env="prod")
            failure, origin, _sha = _establish_deployment_freshness(
                "yoke",
                "main",
                SERVED_SHA,
                context=_context(REQ_MISSING),
                fetch_identity=_asked(SERVED_SHA)[0],
            )
            self.assertIsNotNone(failure)
            self.assertEqual(failure.reason, DEPLOYMENT_RECORD_MISSING)
            self.assertEqual(origin, "")

    def test_malformed_and_unavailable_identity_still_refuse(self):
        with test_database() as conn:
            _seed_prod(conn)
            _seed_item_case(conn, requirement_id=REQ_STANDALONE, target_env="prod")
            context = _context(REQ_STANDALONE)
            malformed, _, _ = _establish_deployment_freshness(
                "yoke",
                "main",
                SERVED_SHA,
                context=context,
                fetch_identity=_asked("not-a-sha")[0],
            )
            self.assertEqual(malformed.reason, IDENTITY_PROOF_MALFORMED)
            unavailable, _, _ = _establish_deployment_freshness(
                "yoke",
                "main",
                SERVED_SHA,
                context=context,
                fetch_identity=_asked("", error="connection refused")[0],
            )
            self.assertEqual(unavailable.reason, IDENTITY_PROOF_UNAVAILABLE)

    def test_an_unbound_item_case_still_has_no_deployment_target(self):
        with test_database() as conn:
            _seed_item_case(conn, requirement_id=REQ_UNBOUND, target_env=None)
            self.assertIsNone(
                resolve_case_deployment_under_test(
                    conn, requirement_id=REQ_UNBOUND, project_id=1
                )
            )
            self.assertIsNone(_context(REQ_UNBOUND).get("deployment_target"))

    def test_a_cross_project_named_environment_fails_closed(self):
        with test_database() as conn:
            conn.execute(
                "INSERT INTO environments (site, project_id, name, url, created_at) "
                "VALUES (2, 2, 'prod', %s, %s)",
                (HOSTED_PLATFORM_URL, NOW),
            )
            conn.commit()
            _seed_item_case(conn, requirement_id=REQ_CROSS, target_env="prod")
            bound = resolve_case_deployment_under_test(
                conn, requirement_id=REQ_CROSS, project_id=1
            )
            assert bound is not None
            self.assertIn("not project 1", bound.unresolved)
            failure, origin, _sha = _establish_deployment_freshness(
                "yoke",
                "main",
                SERVED_SHA,
                context={"deployment_target": bound.as_payload()},
                fetch_identity=_asked(SERVED_SHA)[0],
            )
            self.assertEqual(failure.reason, DEPLOYMENT_TARGET_UNRESOLVED)
            self.assertEqual(origin, "")


class TestRunMemberAndRunAttachedTargets(unittest.TestCase):
    def test_a_run_member_execution_snapshot_outranks_the_item_row(self):
        with test_database() as conn:
            _seed_item_case(conn, requirement_id=REQ_MEMBER, target_env=None)
            frozen = {
                "schema": 2,
                "environment": {"name": "prod"},
                "project": {"id": 1, "slug": "yoke", "name": "Yoke"},
                "endpoints": {
                    "app_url": HOSTED_PLATFORM_URL,
                    "api_url": HOSTED_PLATFORM_URL,
                },
            }
            conn.execute(
                "INSERT INTO qa_plan_executions (id, deployment_run_id, "
                "deployment_stage, deployment_member_item_id, actor_id, "
                "session_id, state, roster_json, roster_digest, cursor_ordinal, "
                "created_at, heartbeat_at, execution_target_json) VALUES "
                "(%s, %s, 'post-deploy-qa', %s, 'op', 's-1', 'active', %s, "
                "'d', 0, %s, %s, %s)",
                (
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    RUN_ID,
                    ITEM_ID,
                    json.dumps([{"requirement_id": REQ_MEMBER}]),
                    NOW,
                    NOW,
                    json.dumps(frozen),
                ),
            )
            conn.commit()
            _seed_prod(conn)
            bound = resolve_case_deployment_under_test(
                conn, requirement_id=REQ_MEMBER, project_id=1
            )
            assert bound is not None
            self.assertEqual(bound.origin, HOSTED_PLATFORM_URL)
            self.assertEqual(bound.environment, "prod")

    def test_a_run_attached_row_resolves_the_run_environment(self):
        with test_database() as conn:
            _seed_prod(conn)
            conn.execute(
                "INSERT INTO project_capabilities "
                "(project_id, type, settings, created_at) "
                "VALUES (1, 'health-endpoint', %s, %s)",
                (json.dumps({"identity_path": IDENTITY_PATH}), NOW),
            )
            conn.commit()
            cursor = conn.execute(
                "SELECT id FROM environments WHERE project_id=1 AND name='prod'"
            )
            environment_id = int(cursor.fetchone()[0])
            insert_deployment_run(
                conn,
                id=RUN_ID,
                status="succeeded",
                target_tier="persistent",
                target_environment_id=environment_id,
            )
            insert_qa_requirement(
                conn,
                id=REQ_RUN,
                item_id=None,
                deployment_run_id=RUN_ID,
                qa_kind="method_case",
                qa_phase="post_deploy",
                method_id="browser-inspection",
            )
            conn.commit()
            bound = resolve_case_deployment_under_test(
                conn, requirement_id=REQ_RUN, project_id=1
            )
            assert bound is not None
            self.assertEqual(bound.environment, "prod")
            self.assertEqual(bound.origin, HOSTED_PLATFORM_URL)
            self.assertEqual(bound.identity_path, IDENTITY_PATH)
