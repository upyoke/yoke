"""The deploy driver's QA fingerprint read tolerates an older serving build.

A self-release driver runs the release's own code against the build already
serving the control plane. That build may predate the cheap fingerprint read:
it ignores ``fingerprint_only`` and answers without a fingerprint. The driver
keeps waiting over HTTPS, re-dispatching every poll, instead of refusing.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.domain import deploy_pipeline_control_plane as control_plane

QA_STAGE = {"step_runner": "qa"}
QA_PENDING = "deployment_runs.execution.qa_pending"


def _answered(result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function=QA_PENDING, version="v1", result=result
    )


def test_served_fingerprint_is_returned(monkeypatch):
    dispatch = Mock(return_value=_answered({"unresolved": [], "fingerprint": "abc"}))
    monkeypatch.setattr(control_plane, "call_dispatcher", dispatch)

    assert control_plane.qa_fingerprint("run-20260101-011", QA_STAGE) == "abc"
    assert dispatch.call_args.kwargs["payload"] == {"fingerprint_only": True}


def test_older_build_without_fingerprint_changes_every_poll_and_is_asked_once(
    monkeypatch,
):
    run_id = "run-20260101-012"
    dispatch = Mock(return_value=_answered({"unresolved": ["requirement #3"]}))
    monkeypatch.setattr(control_plane, "call_dispatcher", dispatch)

    readings = [control_plane.qa_fingerprint(run_id, QA_STAGE) for _ in range(3)]

    assert len(set(readings)) == 3
    assert all(reading for reading in readings)
    assert dispatch.call_count == 1


def test_non_qa_stage_reads_nothing(monkeypatch):
    dispatch = Mock()
    monkeypatch.setattr(control_plane, "call_dispatcher", dispatch)

    assert control_plane.qa_fingerprint("run-20260101-013", {"step_runner": "ecs"}) == ""
    dispatch.assert_not_called()


@pytest.mark.parametrize("code", sorted(control_plane.READ_RETRY_CODES))
@pytest.mark.parametrize("recovers", [True, False])
def test_fingerprint_read_connection_recovery(monkeypatch, code, recovers):
    failed = FunctionCallResponse(
        success=False, function=QA_PENDING, version="v1",
        error=FunctionError(code=code, message="read unavailable"),
    )
    dispatch = Mock(side_effect=[failed, _answered({"fingerprint": "restored"})]
                    if recovers else None, return_value=failed)
    waited = []
    monkeypatch.setattr(control_plane, "call_dispatcher", dispatch)
    monkeypatch.setattr(control_plane.time, "sleep", waited.append)
    run_id = "run-20260101-014"

    if recovers:
        assert control_plane.qa_fingerprint(run_id, QA_STAGE) == "restored"
        assert dispatch.call_count == 2
        assert waited == [control_plane.READ_RETRY_BACKOFF_SECONDS[0]]
    else:
        with pytest.raises(control_plane.DeploymentOutcomeUnknown) as raised:
            control_plane.qa_fingerprint(run_id, QA_STAGE)
        assert f"yoke watch deploy -- {run_id}" in str(raised.value)
        assert dispatch.call_count == len(control_plane.READ_RETRY_BACKOFF_SECONDS) + 1
        assert waited == list(control_plane.READ_RETRY_BACKOFF_SECONDS)
