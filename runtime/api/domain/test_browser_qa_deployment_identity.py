"""Which deployment a run-bound Browser case is about, as the server sees it.

The gap these guard: the context read answered a deployment-run subject from
the branch's ephemeral preview rows, so a production run — which deployed a
registered environment and never published a branch preview — was asked about
a host nothing had deployed, and its own post-deploy visual QA could not be
captured at all.

The server read runs for real here against a disposable database, because
resolving *which* deployment is under test is exactly the boundary that was
wrong. Only the external answer — what a deployment says it is serving — is a
fixture.
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


def _record_stage_observation(
    conn,
    *,
    served: str,
    status: str = "ready",
    run_id: str = RUN_ID,
    target_name: str = ENVIRONMENT,
    artifact_identity: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO deployment_stage_receipts("
        "run_id,stage_name,attempt_number,correlation_id,target_kind,"
        "target_name,status,observed_release_lineage,"
        "observed_artifact_identity,executor,created_at,"
        "completed_at) VALUES (%s,'deploy',1,%s,'persistent_environment',"
        "%s,%s,%s,%s,'test','2026-01-01T00:00:00Z','2026-01-01T00:00:01Z')",
        (
            run_id,
            f"corr-{run_id}",
            target_name,
            status,
            served,
            artifact_identity,
        ),
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

    def test_run_subject_reports_its_environment_and_observation(self):
        with test_database() as conn:
            environment_id = _register_environment(conn)
            _seed_run(conn, environment_id=environment_id)
            _configure_identity_path(conn)
            _record_stage_observation(conn, served=DEPLOYED_SHA)
            conn.commit()
            target = resolve_deployment_under_test(conn, RUN_ID)
        assert target.environment == ENVIRONMENT
        assert target.origin == ENVIRONMENT_URL
        assert target.identity_path == IDENTITY_PATH
        assert target.observed_sha == DEPLOYED_SHA

    def test_a_pending_attempt_is_not_an_observation(self):
        with test_database() as conn:
            environment_id = _register_environment(conn)
            _seed_run(conn, environment_id=environment_id)
            _record_stage_observation(conn, served=DEPLOYED_SHA, status="pending")
            conn.commit()
            target = resolve_deployment_under_test(conn, RUN_ID)
        assert target.observed_sha == ""

    def test_requested_lineage_is_never_reported_as_observed(self):
        """The run pins a candidate; nothing here says it is being served."""
        with test_database() as conn:
            environment_id = _register_environment(conn)
            _seed_run(conn, environment_id=environment_id)
            conn.commit()
            target = resolve_deployment_under_test(conn, RUN_ID)
        assert target.observed_sha == ""

    def test_context_read_returns_the_target_and_no_preview_fields(self):
        with test_database() as conn:
            environment_id = _register_environment(conn)
            _seed_run(conn, environment_id=environment_id)
            _record_stage_observation(conn, served=DEPLOYED_SHA)
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
        assert result["deployment_target"]["observed_sha"] == DEPLOYED_SHA
        assert result["deployment_target"]["environment"] == ENVIRONMENT
        # The branch-preview fields describe a preview this run never made.
        assert result["deployment_recorded"] is False
        assert result["deployed_sha"] is None
        assert result["ephemeral_url"] is None

    def test_another_environments_receipt_is_not_this_deployments_proof(self):
        with test_database() as conn:
            environment_id = _register_environment(conn)
            _seed_run(conn, environment_id=environment_id)
            _record_stage_observation(
                conn, served=DEPLOYED_SHA, target_name="stage"
            )
            conn.commit()
            target = resolve_deployment_under_test(conn, RUN_ID)
        assert target.observed_sha == ""

    def test_another_runs_receipt_is_not_this_runs_proof(self):
        with test_database() as conn:
            environment_id = _register_environment(conn)
            _seed_run(conn, environment_id=environment_id)
            insert_deployment_run(
                conn, id="run-20260101-099", status="succeeded",
            )
            _record_stage_observation(
                conn, served=DEPLOYED_SHA, run_id="run-20260101-099"
            )
            conn.commit()
            target = resolve_deployment_under_test(conn, RUN_ID)
        assert target.observed_sha == ""

    def test_a_receipt_observing_another_artifact_is_not_accepted(self):
        """A run that pins an artifact is proven only by that artifact."""
        with test_database() as conn:
            environment_id = _register_environment(conn)
            insert_deployment_run(
                conn,
                id=RUN_ID,
                status="succeeded",
                release_lineage=OTHER_SHA,
                target_tier="persistent",
                target_environment_id=environment_id,
                artifact_identity="sha256:pinned",
            )
            _record_stage_observation(
                conn, served=DEPLOYED_SHA, artifact_identity="sha256:other",
            )
            conn.commit()
            target = resolve_deployment_under_test(conn, RUN_ID)
        assert target.observed_sha == ""

    def test_an_abbreviated_observation_is_not_a_commit(self):
        with test_database() as conn:
            environment_id = _register_environment(conn)
            _seed_run(conn, environment_id=environment_id)
            _record_stage_observation(conn, served=DEPLOYED_SHA[:12])
            conn.commit()
            target = resolve_deployment_under_test(conn, RUN_ID)
        assert target.observed_sha == ""

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
