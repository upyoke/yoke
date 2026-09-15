"""The deploy driver reaches scoped-QA stage verdicts through call_dispatcher.

Materializing/gating a scoped QA stage and reading a resume's prior
refusals go through the same connection-keyed function-call transport
``deploy_pipeline_control_plane`` uses for every other execution-owned
operation: an admin-bootstrapped driver dispatches in-process, an ordinary
HTTPS-connected driver relays to whatever build is actively serving that
connection. These tests hold the driver to that transport rather than
connecting to the database locally, mirroring
test_deploy_ephemeral_tracking_transport.py.
"""

from __future__ import annotations

from unittest.mock import patch

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.domain import deployment_qa_stage_dispatch as dispatch_mod
from yoke_core.domain import deployment_qa_stage_resume as resume_mod


def _success(function: str, result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function=function, version="v1", result=result
    )


def _failure(function: str, message: str) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=function,
        version="v1",
        error=FunctionError(code="handler_exception", message=message),
    )


def _dispatch_with(response: FunctionCallResponse, *, run_id="run-qa-transport-1"):
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        return response

    with patch(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        side_effect=dispatch,
    ):
        stage = {"name": "member-qa", "scope": "item"}
        outcome = dispatch_mod.dispatch_deployment_qa_stage(stage, run_id=run_id)
    return calls, outcome


def _resume_with(response: FunctionCallResponse, *, run_id="run-qa-transport-1"):
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        return response

    with patch(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        side_effect=dispatch,
    ):
        message = resume_mod.resume_qa_refusal_message(
            run_id=run_id, start_stage="release-qa"
        )
    return calls, message


def test_accepted_stage_lets_the_pipeline_continue():
    _, outcome = _dispatch_with(
        _success(
            dispatch_mod.DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
            {"code": 0, "message": ""},
        )
    )
    assert outcome == (0, "")


def test_durable_qa_wait_is_reported_verbatim():
    calls, outcome = _dispatch_with(
        _success(
            dispatch_mod.DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
            {"code": -4, "message": "member 9: no concrete QA cases are materialized"},
        )
    )
    assert outcome == (-4, "member 9: no concrete QA cases are materialized")
    call = calls[0]
    assert call["function_id"] == dispatch_mod.DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION
    # Only the stage name crosses the wire — the handler derives the rest
    # (scope, config) from the run's own stored flow.
    assert call["payload"] == {"stage_name": "member-qa"}
    assert call["target"].kind == "workflow_run"
    assert call["target"].workflow_run_id == "run-qa-transport-1"


def test_a_refused_dispatch_is_a_named_failure():
    _, outcome = _dispatch_with(
        _failure(dispatch_mod.DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION, "no route")
    )
    code, diagnostic = outcome
    assert code == 1
    assert "no route" in diagnostic


def test_dispatch_never_opens_the_control_plane_database_itself():
    import yoke_core.domain.db_helpers as db_helpers

    def _refuse():
        raise AssertionError("the driver opened the database directly")

    with patch.object(db_helpers, "connect", _refuse):
        _, outcome = _dispatch_with(
            _success(
                dispatch_mod.DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION,
                {"code": 0, "message": ""},
            )
        )
    assert outcome == (0, "")


def test_resume_refusals_are_reported_verbatim():
    calls, message = _resume_with(
        _success(
            resume_mod.RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION,
            {"message": "member 9: no passing case"},
        )
    )
    assert message == "member 9: no passing case"
    call = calls[0]
    assert call["function_id"] == resume_mod.RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION
    # No stage list: the server derives it from the run's own stored flow
    # rather than trusting one from this caller.
    assert call["payload"] == {"start_stage": "release-qa"}
    assert call["target"].workflow_run_id == "run-qa-transport-1"


def test_a_refused_resume_check_raises_rather_than_a_false_clear():
    """A transport failure must never read as 'no scoped QA is outstanding'.

    Returning an empty string here would let a resume skip a real gate
    just because the check could not be evaluated at all.
    """
    try:
        _resume_with(
            _failure(resume_mod.RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION, "no route")
        )
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "no route" in str(exc)


def test_resume_never_opens_the_control_plane_database_itself():
    import yoke_core.domain.db_helpers as db_helpers

    def _refuse():
        raise AssertionError("the driver opened the database directly")

    with patch.object(db_helpers, "connect", _refuse):
        _, message = _resume_with(
            _success(resume_mod.RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION, {"message": ""})
        )
    assert message == ""


def test_the_registered_functions_are_reachable_from_the_dispatcher():
    """A registered operation nobody can invoke is not yet an operation."""
    from yoke_core.domain import yoke_function_registry
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers

    register_all_handlers()  # idempotent; populates the registry if empty
    assert (
        yoke_function_registry.lookup(
            dispatch_mod.DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION
        )
        is not None
    )
    assert (
        yoke_function_registry.lookup(resume_mod.RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION)
        is not None
    )
