"""Deployment result to close-out, on a host holding no customer checkout.

One connected path per deployment shape: something is deployed, a browser
capture is taken against it and its evidence uploaded durably, the recorded
verdict is read back, and the lifecycle gate decides. The two boundaries this
exercises for real are the ones that were wrong — the server-side context read
that resolves which deployment a case is about, and the gate that used to
refuse every Browser requirement for want of a checkout. Both run against a
disposable database with no project checkout anywhere.

Only two things are fixtures, and neither is a boundary under repair: what an
external deployment answers when asked which revision it serves, and the
browser substrate's own writes, which are the capture rather than the
judgment.
"""

from __future__ import annotations

import json
from unittest import mock

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import browser_qa_freshness_outcome as outcome
from yoke_core.domain import served_revision_probe as probe
from yoke_core.domain.browser_qa_freshness import (
    _establish_deployment_freshness,
)
from yoke_core.domain.browser_qa_preview_identity import PreviewIdentityTarget
from yoke_core.domain.handlers import qa_browser
from yoke_core.domain.qa_gate_definitions import GateTarget
from yoke_core.domain.qa_gates import (
    check_done_gate,
    check_reviewed_implementation_gate,
)
from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.fixtures.pg_testdb import test_database


PROJECT = "yoke"
ITEM_ID = 4242
BRANCH = "feature-branch"
DEPLOYED_SHA = "a" * 40
SUPERSEDED_SHA = "f" * 40
RUN_ID = "run-20260101-077"
ENVIRONMENT = "prod"
ENVIRONMENT_URL = "https://app.example.test"
PREVIEW_ORIGIN = "https://feature-branch.preview.example.test"
IDENTITY_PATH = "/candidate-revision"

DURABLE_HANDLE = {
    "backend": "s3",
    "bucket": "tenant-artifacts",
    "key": "tenants/9/qa-artifacts/yoke/4242/1/screenshot.png",
}


def _answers(revision: str):
    """What the deployed thing says when asked which revision it serves."""
    return lambda _url: probe.ServedRevisionRead(status=200, body=revision)


def _seed_item(conn) -> None:
    insert_item(conn, id=ITEM_ID, title="Visual check", status="reviewing-implementation")
    conn.execute(
        "INSERT INTO item_worktrees(item_id,branch,lane_role,state,commit_sha,"
        "created_at,updated_at) VALUES (%s,%s,'implementation','active',%s,"
        "'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')",
        (ITEM_ID, BRANCH, DEPLOYED_SHA),
    )


def _seed_browser_requirement(conn, *, requirement_id: int = 9001) -> int:
    conn.execute(
        "INSERT INTO qa_requirements(id,item_id,qa_kind,qa_phase,blocking_mode,"
        "method_id,verdict_path,method_config,created_at) VALUES "
        "(%s,%s,'plan_case','verification','blocking','browser-check',"
        "'automatic',%s,'2026-01-01T00:00:00Z')",
        (
            requirement_id,
            ITEM_ID,
            json.dumps({"base_url": PREVIEW_ORIGIN}),
        ),
    )
    return requirement_id


def _capture(conn, requirement_id: int, *, sha: str, handle=DURABLE_HANDLE) -> int:
    """Record what the browser substrate captured, and where it uploaded it."""
    from yoke_core.domain.qa_artifact_handle import serialize_handle

    cursor = conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "execution_status,case_outcome,raw_result,completed_at,created_at) "
        "VALUES (%s,'browser_substrate','plan_case','pass','captured','passed',"
        "%s,'2026-01-01T00:01:00Z','2026-01-01T00:01:00Z') RETURNING id",
        (
            requirement_id,
            json.dumps(
                {
                    "project": PROJECT,
                    "base_url": PREVIEW_ORIGIN,
                    "freshness_validated": True,
                    "code_identity": {"branch": BRANCH, "sha": sha},
                }
            ),
        ),
    )
    run_id = int(cursor.fetchone()[0])
    if handle is not None:
        conn.execute(
            "INSERT INTO qa_artifacts(qa_run_id,artifact_type,artifact_handle,"
            "created_at) VALUES (%s,'screenshot',%s,'2026-01-01T00:01:00Z')",
            (run_id, serialize_handle(handle)),
        )
    return run_id


def _context(conn, requirement_id: int, *, run_id: str | None = None) -> dict:
    """The real server-side read, for whichever subject the case names."""
    target = (
        TargetRef(kind="deployment_run", deployment_run_id=run_id)
        if run_id
        else TargetRef(kind="item", item_id=ITEM_ID)
    )
    outcome_ = qa_browser.handle_qa_browser_context_get(
        FunctionCallRequest(
            function="qa.browser_context.get",
            actor=ActorContext(actor_id="op", session_id="s-journey"),
            target=target,
            payload={
                "project": PROJECT,
                "requirement_id": requirement_id,
                "expected_branch": BRANCH,
            },
        ),
    )
    assert outcome_.primary_success, outcome_.error
    return outcome_.result_payload


def _close_out(conn) -> object:
    """The lifecycle gate, on a host where git can answer nothing."""
    conn.commit()
    with mock.patch(
        "yoke_core.domain.qa_gates._resolve_repo_root", return_value=None,
    ):
        return check_done_gate(GateTarget(item_id=ITEM_ID), "")


class TestBranchPreviewJourney:
    def test_a_preview_that_answers_for_itself_closes_out(self):
        with test_database() as conn:
            _seed_item(conn)
            requirement_id = _seed_browser_requirement(conn)
            conn.commit()

            context = _context(conn, requirement_id)
            # No preview row was ever written; the project's own preview
            # publishes what it serves, and that is the deployment result.
            assert context["deployment_recorded"] is False
            with mock.patch(
                "yoke_core.domain.browser_qa_freshness."
                "resolve_preview_identity_target",
                return_value=PreviewIdentityTarget(
                    origin=PREVIEW_ORIGIN, path=IDENTITY_PATH
                ),
            ):
                failure, verified_origin, _sha = _establish_deployment_freshness(
                    PROJECT,
                    BRANCH,
                    DEPLOYED_SHA,
                    context=context,
                    deployment_run_id=None,
                    fetch_identity=_answers(DEPLOYED_SHA),
                )
            assert failure is None
            assert verified_origin == PREVIEW_ORIGIN

            _capture(conn, requirement_id, sha=DEPLOYED_SHA)
            result = _close_out(conn)
        assert result.passed, result.errors

    def test_a_preview_serving_another_commit_refuses(self):
        with test_database() as conn:
            _seed_item(conn)
            requirement_id = _seed_browser_requirement(conn)
            conn.commit()
            context = _context(conn, requirement_id)
            with mock.patch(
                "yoke_core.domain.browser_qa_freshness."
                "resolve_preview_identity_target",
                return_value=PreviewIdentityTarget(
                    origin=PREVIEW_ORIGIN, path=IDENTITY_PATH
                ),
            ):
                failure, verified_origin, _sha = _establish_deployment_freshness(
                    PROJECT,
                    BRANCH,
                    DEPLOYED_SHA,
                    context=context,
                    deployment_run_id=None,
                    fetch_identity=_answers(SUPERSEDED_SHA),
                )
        assert failure is not None
        assert failure.reason == outcome.SHA_MISMATCH
        assert verified_origin == ""


class TestProductionRunJourney:
    def _seed_production_run(self, conn, *, identity_path: str = IDENTITY_PATH):
        cursor = conn.execute(
            "INSERT INTO sites(project_id,name,created_at) VALUES "
            "(1,'Example site','2026-01-01T00:00:00Z') RETURNING id",
        )
        site_id = int(cursor.fetchone()[0])
        cursor = conn.execute(
            "INSERT INTO environments(site,project_id,name,url,created_at) "
            "VALUES (%s,1,%s,%s,'2026-01-01T00:00:00Z') RETURNING id",
            (site_id, ENVIRONMENT, ENVIRONMENT_URL),
        )
        environment_id = int(cursor.fetchone()[0])
        if identity_path:
            conn.execute(
                "INSERT INTO project_capabilities(project_id,type,settings,"
                "created_at) VALUES (1,'health-endpoint',%s,"
                "'2026-01-01T00:00:00Z')",
                (json.dumps({"identity_path": identity_path}),),
            )
        insert_deployment_run(
            conn,
            id=RUN_ID,
            status="succeeded",
            release_lineage=DEPLOYED_SHA,
            target_tier="persistent",
            target_environment_id=environment_id,
        )
        conn.execute(
            "INSERT INTO qa_requirements(id,deployment_run_id,qa_kind,qa_phase,"
            "blocking_mode,method_id,verdict_path,method_config,created_at) "
            "VALUES (9100,%s,'plan_case','post_deploy','blocking',"
            "'browser-check','automatic',%s,'2026-01-01T00:00:00Z')",
            (RUN_ID, json.dumps({"base_url": ENVIRONMENT_URL})),
        )
        conn.commit()
        return 9100

    def test_the_run_reaches_its_own_environment_not_a_branch_preview(self):
        with test_database() as conn:
            requirement_id = self._seed_production_run(conn)
            context = _context(conn, requirement_id, run_id=RUN_ID)
            assert context["deployment_target"]["environment"] == ENVIRONMENT
            failure, verified_origin, _sha = _establish_deployment_freshness(
                PROJECT,
                BRANCH,
                DEPLOYED_SHA,
                context=context,
                deployment_run_id=RUN_ID,
                fetch_identity=_answers(DEPLOYED_SHA),
            )
        assert failure is None
        # Evidence may be collected from the proven environment and nowhere
        # else; this is what the scenario binds execution against.
        assert verified_origin == ENVIRONMENT_URL

    def test_an_environment_serving_another_commit_refuses(self):
        with test_database() as conn:
            requirement_id = self._seed_production_run(conn)
            context = _context(conn, requirement_id, run_id=RUN_ID)
            failure, _, _sha = _establish_deployment_freshness(
                PROJECT,
                BRANCH,
                DEPLOYED_SHA,
                context=context,
                deployment_run_id=RUN_ID,
                fetch_identity=_answers(SUPERSEDED_SHA),
            )
        assert failure is not None
        assert failure.reason == outcome.SHA_MISMATCH

    def test_an_environment_that_publishes_nothing_refuses_by_name(self):
        with test_database() as conn:
            requirement_id = self._seed_production_run(conn, identity_path="")
            context = _context(conn, requirement_id, run_id=RUN_ID)
            failure, _, _sha = _establish_deployment_freshness(
                PROJECT,
                BRANCH,
                DEPLOYED_SHA,
                context=context,
                deployment_run_id=RUN_ID,
                fetch_identity=_answers(DEPLOYED_SHA),
            )
        assert failure is not None
        assert failure.reason == outcome.DEPLOYMENT_RECORD_MISSING
        assert "identity_path" in failure.message


class TestCloseOutRefusals:
    def test_a_capture_of_a_superseded_commit_is_refused(self):
        with test_database() as conn:
            _seed_item(conn)
            requirement_id = _seed_browser_requirement(conn)
            _capture(conn, requirement_id, sha=SUPERSEDED_SHA)
            result = _close_out(conn)
        assert not result.passed
        joined = "\n".join(result.errors)
        assert "stale passing runs" in joined
        assert DEPLOYED_SHA in joined

    def test_evidence_recorded_where_this_host_cannot_read_it_is_refused(self):
        with test_database() as conn:
            _seed_item(conn)
            requirement_id = _seed_browser_requirement(conn)
            _capture(
                conn,
                requirement_id,
                sha=DEPLOYED_SHA,
                handle={"backend": "local", "path": "artifacts/shot.png"},
            )
            result = _close_out(conn)
        assert not result.passed
        joined = "\n".join(result.errors)
        assert "GATE_QA_BROWSER_PROOF_NEEDS_CHECKOUT" in joined
        assert "checkout-relative path" in joined

    def test_a_capture_with_no_evidence_at_all_is_refused(self):
        """Evidence presence is the verification gate's refusal, not done's.

        A checkout-less host reaches that gate exactly as one with a checkout
        does, which is the property under test here; the done gate relies on
        it having already run rather than re-asserting it.
        """
        with test_database() as conn:
            _seed_item(conn)
            requirement_id = _seed_browser_requirement(conn)
            _capture(conn, requirement_id, sha=DEPLOYED_SHA, handle=None)
            conn.commit()
            with mock.patch(
                "yoke_core.domain.qa_gates._resolve_repo_root", return_value=None,
            ):
                result = check_reviewed_implementation_gate(
                    GateTarget(item_id=ITEM_ID), "",
                )
        assert not result.passed
        assert any("substrate evidence" in error for error in result.errors)
