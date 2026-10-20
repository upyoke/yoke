"""Callers of a busy run retry on a schedule instead of failing or piling up.

The deploy driver re-dispatches a QA or approval stage refused as busy on its
next check and repeats a busy bookkeeping call with backoff; neither fails the
run. ``yoke qa plan run`` and ``yoke qa case run`` -- the children of the
``yoke watch qa-plan`` and ``qa-case`` wrappers -- back off 15s, 30s, then 60s
and stop with a named reason after the cap.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_core.domain import deploy_pipeline_control_plane as control_plane
from yoke_core.domain import deployment_qa_stage_dispatch as dispatch_mod
from yoke_core.domain import qa_plan_execution_checkin as checkin
from yoke_core.domain.control_plane_transport import ControlPlaneRefused
from yoke_core.domain.deploy_pipeline_qa_wait import (
    AWAITING_SCOPED_QA,
    RETRY_NEXT_CHECK,
    dispatch_until_qa_resolves,
)
from yoke_core.domain.deploy_pipeline_unknown_outcome import (
    DeploymentRunStayedBusy,
    preserve_unknown_outcome,
)
from yoke_core.domain.deployment_runs_lock import RUN_BUSY_CODE
from yoke_core.domain.deployment_stage_approval_dispatch import (
    dispatch_deployment_stage_approval,
)
from yoke_core.domain.function_lock_refusal import (
    LOCK_RETRY_DELAYS_SECONDS,
    RETRYABLE_LOCK_CODES,
)
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError

_RUN = "run-20261020-003"
_BUSY = f"{RUN_BUSY_CODE}: deployment run '{_RUN}' row was not free: pid 9 has held it"


def _refused(code: str, function: str = "f") -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=function,
        version="v1",
        error=FunctionError(code=code, message=_BUSY),
    )


def _ok(result: dict, function: str = "f") -> FunctionCallResponse:
    return FunctionCallResponse(success=True, function=function, version="v1", result=result)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_the_driver_re_dispatches_a_busy_stage_on_its_next_check() -> None:
    clock = _Clock()
    outcomes = iter([(RETRY_NEXT_CHECK, _BUSY), (0, "accepted")])

    result = dispatch_until_qa_resolves(
        lambda: next(outcomes),
        timeout_seconds=1800,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result == (0, "accepted")
    assert clock.sleeps == [15.0]


def test_a_run_busy_past_the_wait_stops_resumably_and_is_not_failed() -> None:
    clock = _Clock()

    code, diagnostic = dispatch_until_qa_resolves(
        lambda: (RETRY_NEXT_CHECK, _BUSY),
        timeout_seconds=31,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert code == AWAITING_SCOPED_QA
    assert _BUSY in diagnostic
    assert "was not failed" in diagnostic


@pytest.mark.parametrize("code", sorted(RETRYABLE_LOCK_CODES))
def test_a_refused_or_cancelled_qa_dispatch_asks_again(code: str) -> None:
    with patch(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        return_value=_refused(code),
    ):
        result = dispatch_mod.dispatch_deployment_qa_stage(
            {"name": "item-qa", "scope": "item"}, run_id=_RUN
        )
    assert result == (RETRY_NEXT_CHECK, _BUSY)


def test_a_busy_approval_evaluation_asks_again() -> None:
    with patch(
        "yoke_core.domain.control_plane_transport.serving_authority",
        side_effect=ControlPlaneRefused(_BUSY, code=RUN_BUSY_CODE),
    ):
        assert dispatch_deployment_stage_approval(_RUN, "approve") == (
            RETRY_NEXT_CHECK,
            _BUSY,
        )


def test_a_busy_bookkeeping_write_repeats_with_backoff(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(control_plane.time, "sleep", sleeps.append)
    answers = iter([_refused(RUN_BUSY_CODE)] * 2 + [_ok({"updated": True})])
    monkeypatch.setattr(control_plane, "call_dispatcher", lambda **_: next(answers))

    control_plane.update_run_field(_RUN, "current_stage", "item-qa")

    assert sleeps == [15.0, 30.0]


def test_a_write_busy_past_every_retry_stops_the_driver_unchanged(monkeypatch, capsys) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(control_plane.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        control_plane, "call_dispatcher", lambda **_: _refused(RUN_BUSY_CODE)
    )
    failed: list[str] = []

    @preserve_unknown_outcome
    def drive() -> int:
        try:
            control_plane.update_run_field(_RUN, "current_stage", "item-qa")
        except control_plane.DeploymentControlPlaneError:
            failed.append("stage failure path")
        return 0

    assert drive() == 1
    assert failed == []
    assert sleeps == list(LOCK_RETRY_DELAYS_SECONDS)
    err = capsys.readouterr().err
    assert "deployment_run_stayed_busy" in err
    assert f"all {len(LOCK_RETRY_DELAYS_SECONDS) + 1} attempts" in err
    assert "was not failed" in err
    assert f"yoke watch deploy -- {_RUN}" in err
    assert issubclass(DeploymentRunStayedBusy, RuntimeError)


def _deliver(monkeypatch, answers):
    sleeps: list[float] = []
    request_ids: list[str] = []
    monkeypatch.setattr(checkin.time, "sleep", sleeps.append)

    def call(**kwargs):
        request_ids.append(kwargs["request_id"])
        return next(answers)

    monkeypatch.setattr("yoke_core.domain.qa_composed_dispatch.call_qa_function", call)
    result = checkin.deliver_plan_function(
        function_id="qa.plan_execution.begin",
        target=TargetRef(kind="workflow_run", workflow_run_id=_RUN),
        payload={},
        actor=SimpleNamespace(),
    )
    return result, sleeps, request_ids


def test_a_qa_walk_backs_off_on_run_busy_then_proceeds(monkeypatch) -> None:
    answers = iter([_refused(RUN_BUSY_CODE)] * 2 + [_ok({"execution_id": "x"})])

    result, sleeps, request_ids = _deliver(monkeypatch, answers)

    assert result == {"execution_id": "x"}
    assert sleeps == [15.0, 30.0]
    # A busy request ran nothing, so each repeat is a new request.
    assert len(set(request_ids)) == 3


def test_a_qa_walk_stops_with_a_named_reason_after_its_cap(monkeypatch) -> None:
    answers = iter([_refused(RUN_BUSY_CODE)] * 20)

    with pytest.raises(QaPlanExecutionError) as raised:
        _deliver(monkeypatch, answers)

    text = str(raised.value)
    assert text.startswith("run_busy_retries_exhausted: qa.plan_execution.begin")
    assert f"all {len(LOCK_RETRY_DELAYS_SECONDS) + 1} attempts" in text
    assert _BUSY in text
    assert LOCK_RETRY_DELAYS_SECONDS == (15.0, 30.0, 60.0, 60.0, 60.0, 60.0)
