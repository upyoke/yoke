"""Which deployment a run-bound Browser case is about, as the server sees it.

The gap these guard: the context read answered a deployment-run subject from
the branch's ephemeral preview rows, so a production run — which deployed a
registered environment and never published a branch preview — was asked about
a host nothing had deployed, and its own post-deploy visual QA could not be
captured at all.

The server read runs for real here against a disposable database, because
resolving *which* deployment is under test is exactly the boundary that was
wrong. What that deployment is SERVING is a separate, present-tense question
its sibling suite covers; resolution deliberately carries no stored answer to
it.
"""

from __future__ import annotations

import json

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.browser_qa_deployment_identity import (
    resolve_deployment_under_test,
)
from yoke_core.domain.handlers import qa_browser
from runtime.api.fixtures.backlog_inserts import insert_deployment_run
from runtime.api.fixtures.pg_testdb import test_database


RUN_ID = "run-20260101-042"
DEPLOYED_SHA = "c" * 40
OTHER_SHA = "d" * 40
ENVIRONMENT = "prod"
ENVIRONMENT_URL = "https://app.example.test"
IDENTITY_PATH = "/candidate-revision"


def _register_environment(conn, *, url: str = ENVIRONMENT_URL) -> int:
    cursor = conn.execute(
        "INSERT INTO sites(project_id,name,created_at) VALUES "
        "(1,'Example site','2026-01-01T00:00:00Z') RETURNING id",
    )
    site_id = int(cursor.fetchone()[0])
    cursor = conn.execute(
        "INSERT INTO environments(site,project_id,name,url,created_at) "
        "VALUES (%s,1,%s,%s,'2026-01-01T00:00:00Z') RETURNING id",
        (site_id, ENVIRONMENT, url or None),
    )
    return int(cursor.fetchone()[0])


def _configure_identity_path(conn, path: str = IDENTITY_PATH) -> None:
    conn.execute(
        "INSERT INTO project_capabilities(project_id,type,settings,created_at) "
        "VALUES (1,'health-endpoint',%s,'2026-01-01T00:00:00Z')",
        (json.dumps({"identity_path": path}),),
    )


def _record_stage_observation(conn, *, served: str) -> None:
    """A ready receipt for this run and environment — deliberately ignored."""
    conn.execute(
        "INSERT INTO deployment_stage_receipts("
        "run_id,stage_name,attempt_number,correlation_id,target_kind,"
        "target_name,status,observed_release_lineage,executor,created_at,"
        "completed_at) VALUES (%s,'deploy',1,'corr-1','persistent_environment',"
        "%s,'ready',%s,'test','2026-01-01T00:00:00Z','2026-01-01T00:00:01Z')",
        (RUN_ID, ENVIRONMENT, served),
    )


def _seed_run(conn, *, environment_id: int | None) -> None:
    # A run only carries the persistent tier when it names an environment;
    # the schema refuses the pair any other way.
    insert_deployment_run(
        conn,
        id=RUN_ID,
        status="succeeded",
        release_lineage=OTHER_SHA,
        target_tier="persistent" if environment_id is not None else None,
        target_environment_id=environment_id,
    )


class TestServerResolution:
    """What the control plane reports about the deployment under test."""

    def test_run_subject_reports_its_environment_and_how_to_ask_it(self):
        with test_database() as conn:
            environment_id = _register_environment(conn)
            _seed_run(conn, environment_id=environment_id)
            _configure_identity_path(conn)
            conn.commit()
            target = resolve_deployment_under_test(conn, RUN_ID)
        assert target.environment == ENVIRONMENT
        assert target.origin == ENVIRONMENT_URL
        assert target.identity_path == IDENTITY_PATH

    def test_no_stored_revision_is_carried_for_the_judgment_to_reuse(self):
        """A ready receipt says what was served THEN, so it is not carried.

        The environment this run deployed is shared and mutable: a later run
        replaces what it serves while this receipt keeps naming this run's
        candidate. Carrying it would hand the freshness judgment a stale
        answer, so resolution reports only where to ask.
        """
        with test_database() as conn:
            environment_id = _register_environment(conn)
            _seed_run(conn, environment_id=environment_id)
            _configure_identity_path(conn)
            _record_stage_observation(conn, served=DEPLOYED_SHA)
            conn.commit()
            target = resolve_deployment_under_test(conn, RUN_ID)
            payload = target.as_payload()
        assert "observed_sha" not in payload
        assert DEPLOYED_SHA not in str(payload)

    def test_context_read_returns_the_target_and_no_preview_fields(self):
        with test_database() as conn:
            environment_id = _register_environment(conn)
            _seed_run(conn, environment_id=environment_id)
            _configure_identity_path(conn)
            conn.execute(
                "INSERT INTO qa_requirements(id,deployment_run_id,qa_kind,"
                "qa_phase,blocking_mode,method_id,method_config,created_at) "
                "VALUES (7001,%s,'plan_case','post_deploy','blocking',"
                "'browser-inspection','{\"base_url\":\"%s\"}',"
                "'2026-01-01T00:00:00Z')" % ("%s", ENVIRONMENT_URL),
                (RUN_ID,),
            )
            conn.commit()
            result = qa_browser.handle_qa_browser_context_get(
                FunctionCallRequest(
                    function="qa.browser_context.get",
                    actor=ActorContext(actor_id="op", session_id="s-1"),
                    target=TargetRef(
                        kind="deployment_run", deployment_run_id=RUN_ID
                    ),
                    payload={
                        "project": "yoke",
                        "requirement_id": 7001,
                        "expected_branch": "main",
                    },
                ),
            ).result_payload
        assert result["deployment_target"]["environment"] == ENVIRONMENT
        assert result["deployment_target"]["identity_path"] == IDENTITY_PATH
        # The branch-preview fields describe a preview this run never made.
        assert result["deployment_recorded"] is False
        assert result["deployed_sha"] is None
        assert result["ephemeral_url"] is None

    def test_an_unregistered_run_resolves_to_nothing(self):
        with test_database() as conn:
            target = resolve_deployment_under_test(conn, "run-does-not-exist")
        assert "not registered" in target.unresolved

    def test_a_run_targeting_no_environment_resolves_to_nothing(self):
        with test_database() as conn:
            _seed_run(conn, environment_id=None)
            conn.commit()
            target = resolve_deployment_under_test(conn, RUN_ID)
        assert "targets no registered environment" in target.unresolved
