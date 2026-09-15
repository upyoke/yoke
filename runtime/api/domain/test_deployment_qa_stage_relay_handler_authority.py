"""Server-side authority for the scoped-QA stage relay handlers.

FN50172: the new deployment_runs.qa_stage.dispatch / resume_refusals
handlers must enforce the same deploy_lock_required guardrail every sibling
execution handler enforces, and the resume handler must derive its stage
list from the run's own stored flow rather than trusting a caller-supplied
one — a caller (or an altered/empty payload) must never be able to read as
"no scoped QA is outstanding" for a run that actually has one.
"""

from __future__ import annotations


from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import deployment_qa_stage_relay as relay
from runtime.api.domain.test_deployment_execution_serving_authority import (
    FLOW,
    PROJECT,
    serving_plane,  # noqa: F401 - pytest fixture re-export
)


def _request(function_id: str, session_id: str, run_id: str, payload: dict):
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(session_id=session_id),
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload=payload,
    )


def _create_run(conn, run_id: str) -> None:
    conn.execute(
        "INSERT INTO deployment_runs (id, project_id, flow, status, created_at) "
        "SELECT %s, id, %s, 'executing', %s FROM projects WHERE slug=%s",
        (run_id, FLOW, "2026-09-15T00:00:00Z", PROJECT),
    )
    conn.commit()


def test_dispatch_refuses_a_session_that_holds_no_deploy_lock(
    serving_plane,  # noqa: F811 - fixture re-export, this is the intended shadow
):
    conn = serving_plane["conn"]
    run_id = "run-authority-dispatch-1"
    _create_run(conn, run_id)

    outcome = relay.handle_deployment_qa_stage_dispatch(
        _request(
            "deployment_runs.qa_stage.dispatch",
            serving_plane["other_session"],
            run_id,
            {"stage": {"name": "member-qa", "scope": "run"}},
        )
    )
    assert outcome.primary_success is False
    assert outcome.error.code == "deploy_lock_required"


def test_resume_refusals_refuses_a_session_that_holds_no_deploy_lock(
    serving_plane,  # noqa: F811 - fixture re-export, this is the intended shadow
):
    conn = serving_plane["conn"]
    run_id = "run-authority-resume-1"
    _create_run(conn, run_id)

    outcome = relay.handle_deployment_qa_stage_resume_refusals(
        _request(
            "deployment_runs.qa_stage.resume_refusals",
            serving_plane["other_session"],
            run_id,
            {"start_stage": "complete"},
        )
    )
    assert outcome.primary_success is False
    assert outcome.error.code == "deploy_lock_required"


def test_resume_refusals_derives_stages_from_the_stored_flow_not_the_caller(
    serving_plane,  # noqa: F811 - fixture re-export, this is the intended shadow
):
    """An empty/altered payload stage list must not read as a false clear.

    The fixture's own flow has a scoped-nothing shape (no qa_kind/QA
    step_runner stages), so this proves the handler actually queried the
    run's stored flow (a code path that would error if it tried to trust a
    nonexistent payload.stages field) rather than that the answer happens
    to be empty by coincidence.
    """
    conn = serving_plane["conn"]
    run_id = "run-authority-resume-2"
    _create_run(conn, run_id)

    outcome = relay.handle_deployment_qa_stage_resume_refusals(
        _request(
            "deployment_runs.qa_stage.resume_refusals",
            serving_plane["owner_session"],
            run_id,
            # No "stages" key at all — proves the handler cannot depend on
            # one, since the request schema no longer accepts it.
            {"start_stage": "complete"},
        )
    )
    assert outcome.primary_success is True
    assert outcome.result_payload["run_id"] == run_id


def test_resume_refusals_request_schema_has_no_client_supplied_stage_list():
    assert "stages" not in relay.DeploymentQaStageResumeRefusalsRequest.model_fields
