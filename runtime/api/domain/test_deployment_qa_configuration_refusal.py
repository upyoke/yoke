"""A QA configuration refusal stops the driver; it never fails the run.

A saved plan the gate refuses is fixable configuration. The stage answers
``qa_configuration_refused`` with the recovery, and the driver exits without
recording the run failed, so every member's passed QA is kept. Any other
stage error still fails the stage as before.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.domain.test_deploy_pipeline_scoped_qa_reporting import (  # noqa: F401
    awaiting_driver,
    scoped_run,
)
from runtime.api.domain.test_deployment_qa_stage_dispatch_close_order import (
    RUN_ID,
    SETTLED_MEMBER,
    STAGE,
    WAITING_MEMBER,
    _Conn,
    _status,
)
from yoke_core.domain import deploy_pipeline as pipeline
from yoke_core.domain import deployment_qa_stage_dispatch as dispatch
from yoke_core.domain import deployment_qa_stage_gate as gate
from yoke_core.domain.deployment_qa_configuration_refusal import (
    QA_CONFIGURATION_REFUSED,
)
from yoke_core.domain.qa_plan_management import QaPlanError

SNAPSHOT_MISSING = (
    "qa_plan_source_snapshot_missing: this frozen plan predates source binding; "
    "retain its evidence and select a source-proven plan for the candidate, or "
    "use a run-bound correction."
)


def _gate_with(error: Exception) -> tuple[int, str, list[int]]:
    def gated(conn, *, member_item_id, **kw):
        if member_item_id == WAITING_MEMBER:
            raise error
        return _status(conn, member_item_id=member_item_id, **kw)

    closed: list[int] = []
    with (
        patch.object(gate, "deployment_qa_stage_status", side_effect=gated),
        patch.object(dispatch, "removed_item_ids", return_value=set()),
        patch.object(dispatch, "report_stage_result"),
        patch(
            "yoke_core.domain.deployment_qa_member_acceptance_notice."
            "notify_items_qa_accepted",
            side_effect=lambda conn, **kw: closed.extend(kw["item_ids"]),
        ),
    ):
        code, message = dispatch.materialize_and_gate_deployment_qa_stage(
            _Conn(), STAGE, run_id=RUN_ID
        )
    return code, message, closed


def test_plan_refusal_answers_configuration_refused_with_recovery() -> None:
    code, message, closed = _gate_with(QaPlanError(SNAPSHOT_MISSING))

    assert code == QA_CONFIGURATION_REFUSED
    assert message.startswith(f"qa_configuration_refused: {SNAPSHOT_MISSING}")
    assert f"Run {RUN_ID} stays executing at stage 'item-qa'" in message
    assert "was not failed" in message
    assert f"`yoke watch deploy -- {RUN_ID}`" in message
    # Members accepted before the refusal keep their close-out.
    assert closed == [SETTLED_MEMBER]


def test_other_gate_errors_still_fail_the_stage() -> None:
    code, message, _ = _gate_with(LookupError("member snapshot is unreadable"))

    assert (code, message) == (1, "member snapshot is unreadable")


@pytest.fixture
def stage_failures(awaiting_driver, monkeypatch):  # noqa: F811
    failed: list[dict] = []
    monkeypatch.setattr(
        pipeline.deploy_pipeline_failure,
        "fail_pipeline_stage",
        lambda **kw: failed.append(kw) or pipeline.EXIT_STAGE_FAILED,
    )
    return awaiting_driver[0], failed


def test_driver_stops_without_failing_the_run(stage_failures, monkeypatch, capsys):
    run_id, failed = stage_failures
    refusal = f"qa_configuration_refused: {SNAPSHOT_MISSING} Recovery: re-drive."
    monkeypatch.setattr(
        pipeline,
        "dispatch_until_qa_resolves",
        lambda *a, **k: (QA_CONFIGURATION_REFUSED, refusal),
    )

    assert pipeline.run_pipeline(run_id, sd="/tmp/sd") == pipeline.EXIT_STAGE_FAILED
    assert failed == []
    assert refusal in capsys.readouterr().err


def test_driver_still_fails_the_run_on_a_real_stage_failure(
    stage_failures, monkeypatch
):
    run_id, failed = stage_failures
    monkeypatch.setattr(
        pipeline, "dispatch_until_qa_resolves", lambda *a, **k: (1, "QA failed")
    )

    assert pipeline.run_pipeline(run_id, sd="/tmp/sd") == pipeline.EXIT_STAGE_FAILED
    assert [(f["exit_code"], f["diagnostic"]) for f in failed] == [(1, "QA failed")]
