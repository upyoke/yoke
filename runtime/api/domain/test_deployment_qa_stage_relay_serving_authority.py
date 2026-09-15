"""The deploy driver asks the serving build for scoped-QA stage verdicts.

An ordinary project deploy runs over HTTPS only — the driver holds no local
database authority to materialize/gate a scoped QA stage or evaluate a
resume's prior refusals. These tests hold the driver to asking the serving
control plane instead of connecting locally, mirroring
test_deployment_stage_approval_serving_authority.py.
"""

from __future__ import annotations

from yoke_core.domain import control_plane_transport
from yoke_core.domain import deployment_qa_stage_dispatch as dispatch_mod
from yoke_core.domain import deployment_qa_stage_resume as resume_mod


class _RecordedCall:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple] = []

    def __call__(self, function_id, payload, target=None):
        self.calls.append((function_id, payload, target))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _dispatch_with(monkeypatch, result, *, run_id="run-serving-qa-1"):
    recorder = _RecordedCall(result)
    monkeypatch.setattr(dispatch_mod, "serving_authority", recorder, raising=False)
    monkeypatch.setattr(control_plane_transport, "serving_authority", recorder)
    stage = {"name": "member-qa", "scope": "item"}
    outcome = dispatch_mod.dispatch_deployment_qa_stage(stage, run_id=run_id)
    return recorder, outcome


def _resume_with(monkeypatch, result, *, run_id="run-serving-qa-1"):
    recorder = _RecordedCall(result)
    monkeypatch.setattr(resume_mod, "serving_authority", recorder, raising=False)
    monkeypatch.setattr(control_plane_transport, "serving_authority", recorder)
    message = resume_mod.resume_qa_refusal_message(
        run_id=run_id, start_stage="release-qa"
    )
    return recorder, message


def test_accepted_stage_lets_the_pipeline_continue(monkeypatch):
    _, outcome = _dispatch_with(monkeypatch, {"code": 0, "message": ""})
    assert outcome == (0, "")


def test_durable_qa_wait_is_reported_verbatim(monkeypatch):
    recorder, outcome = _dispatch_with(
        monkeypatch,
        {"code": -4, "message": "member 9: no concrete QA cases are materialized"},
    )
    assert outcome == (-4, "member 9: no concrete QA cases are materialized")
    function_id, payload, target = recorder.calls[0]
    assert function_id == dispatch_mod.DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION
    assert payload == {"stage": {"name": "member-qa", "scope": "item"}}
    assert target.kind == "workflow_run"
    assert target.workflow_run_id == "run-serving-qa-1"


def test_an_unreachable_serving_plane_is_a_named_dispatch_failure(monkeypatch):
    _, outcome = _dispatch_with(monkeypatch, RuntimeError("relay refused: no route"))
    code, diagnostic = outcome
    assert code == 1
    assert "serving control plane" in diagnostic
    assert "no route" in diagnostic


def test_dispatch_never_opens_the_control_plane_database_itself(monkeypatch):
    import yoke_core.domain.db_helpers as db_helpers

    def _refuse():
        raise AssertionError("the driver opened the serving database")

    monkeypatch.setattr(db_helpers, "connect", _refuse)
    _, outcome = _dispatch_with(monkeypatch, {"code": 0, "message": ""})
    assert outcome == (0, "")


def test_resume_refusals_are_reported_verbatim(monkeypatch):
    recorder, message = _resume_with(
        monkeypatch, {"message": "member 9: no passing case"}
    )
    assert message == "member 9: no passing case"
    function_id, payload, target = recorder.calls[0]
    assert function_id == resume_mod.RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION
    # No stage list: the serving side derives it from the run's own stored
    # flow rather than trusting one from this caller.
    assert payload == {"start_stage": "release-qa"}
    assert target.workflow_run_id == "run-serving-qa-1"


def test_an_unreachable_serving_plane_raises_rather_than_a_false_clear(monkeypatch):
    """A transport failure must never read as 'no scoped QA is outstanding'.

    Returning an empty string here would let a resume skip a real gate
    just because the serving plane could not be reached.
    """
    recorder = _RecordedCall(RuntimeError("relay refused: no route"))
    monkeypatch.setattr(resume_mod, "serving_authority", recorder, raising=False)
    monkeypatch.setattr(control_plane_transport, "serving_authority", recorder)
    try:
        resume_mod.resume_qa_refusal_message(
            run_id="run-serving-qa-1", start_stage="release-qa"
        )
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "no route" in str(exc)


def test_resume_never_opens_the_control_plane_database_itself(monkeypatch):
    import yoke_core.domain.db_helpers as db_helpers

    def _refuse():
        raise AssertionError("the driver opened the serving database")

    monkeypatch.setattr(db_helpers, "connect", _refuse)
    _, message = _resume_with(monkeypatch, {"message": ""})
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
