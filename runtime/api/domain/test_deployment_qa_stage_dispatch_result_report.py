"""The dispatch reports a settled stage result, and only a settled one.

The wiring half of the QA-result notification: whether the pipeline's own
QA-stage dispatch hands the stage's configured audience its outcome.
``test_deployment_qa_result_notice.py`` owns what that notice contains
and who it resolves to; these cases own when dispatch reports at all,
for an item-scoped and a run-scoped stage, and that a stage still
waiting is reported to nobody because the wake already addressed it.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

from runtime.api.domain.test_deployment_qa_stage_dispatch_wake import _member, _run
from yoke_core.domain import deployment_qa_stage_dispatch as dispatch_mod
from yoke_core.domain.deployment_qa_result_notice import (
    OUTCOME_PASSED,
    OUTCOME_REJECTED,
)
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)

_NOTIFICATION = {
    "enabled": True,
    "recipients": {"item_owners": True},
}


def _status(outcome: str, *, accepted: bool, reasons=()):
    return {
        "accepted": accepted,
        "outcome": outcome,
        "reasons": list(reasons),
        "request_id": None,
        "target_digest": "digest-9",
    }


def _dispatch(conn, stage, *, run_id, status):
    with (
        mock.patch(
            "yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status",
            return_value=status,
        ),
        mock.patch(
            "yoke_core.domain.deployment_qa_stage_materialization"
            ".materialize_deployment_qa_stage"
        ),
        mock.patch.object(
            dispatch_mod, "notify_item_scoped_qa_wait", return_value="delivered"
        ),
        mock.patch.object(
            dispatch_mod, "notify_run_scoped_qa_wait", return_value="delivered"
        ),
        mock.patch.object(
            dispatch_mod,
            "notify_qa_stage_result",
            return_value={"notified": [7], "message_id": "m-1", "reason": ""},
        ) as report,
    ):
        result = materialize_and_gate_deployment_qa_stage(conn, stage, run_id=run_id)
    return result, report


def test_an_accepted_item_scoped_stage_is_reported(test_db: Any) -> None:
    _run(test_db, "run-report-1")
    _member(test_db, "run-report-1", 9611)
    stage = {"name": "item-qa", "scope": "item", "notification": _NOTIFICATION}

    (rc, _diag), report = _dispatch(
        test_db,
        stage,
        run_id="run-report-1",
        status=_status(OUTCOME_PASSED, accepted=True),
    )

    assert rc == 0
    report.assert_called_once()
    kwargs = report.call_args.kwargs
    assert kwargs["outcome"] == OUTCOME_PASSED
    assert kwargs["member_item_id"] == 9611
    assert kwargs["notification"] == _NOTIFICATION
    assert kwargs["target_digest"] == "digest-9"
    assert kwargs["subject"].endswith("-9611")


def test_a_rejected_item_scoped_stage_is_reported_and_still_waits(
    test_db: Any,
) -> None:
    """A rejection is both a result to report and a stage that holds."""
    _run(test_db, "run-report-2")
    _member(test_db, "run-report-2", 9612)
    stage = {"name": "item-qa", "scope": "item", "notification": _NOTIFICATION}

    (rc, diag), report = _dispatch(
        test_db,
        stage,
        run_id="run-report-2",
        status=_status(
            OUTCOME_REJECTED, accepted=False, reasons=["requirement #5 was rejected"]
        ),
    )

    assert rc == -4
    assert "was rejected" in diag
    assert report.call_args.kwargs["outcome"] == OUTCOME_REJECTED


def test_a_run_scoped_result_reports_the_batch(test_db: Any) -> None:
    _run(test_db, "run-report-3")
    stage = {"name": "release-qa", "scope": "run", "notification": _NOTIFICATION}

    (rc, _diag), report = _dispatch(
        test_db,
        stage,
        run_id="run-report-3",
        status=_status(OUTCOME_PASSED, accepted=True),
    )

    assert rc == 0
    kwargs = report.call_args.kwargs
    assert kwargs["member_item_id"] is None
    assert kwargs["subject"] == "the whole release batch"


def test_a_waiting_stage_reports_no_result(test_db: Any) -> None:
    _run(test_db, "run-report-4")
    _member(test_db, "run-report-4", 9614)
    stage = {"name": "item-qa", "scope": "item", "notification": _NOTIFICATION}

    (rc, _diag), report = _dispatch(
        test_db,
        stage,
        run_id="run-report-4",
        status=_status("waiting", accepted=False, reasons=["awaiting agent verdict"]),
    )

    assert rc == -4
    report.assert_not_called()


def test_a_report_failure_does_not_fail_the_stage(test_db: Any, capsys) -> None:
    """The QA answer is the durable outcome; reporting it is best effort."""
    _run(test_db, "run-report-5")
    _member(test_db, "run-report-5", 9615)
    stage = {"name": "item-qa", "scope": "item", "notification": _NOTIFICATION}

    with (
        mock.patch(
            "yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status",
            return_value=_status(OUTCOME_PASSED, accepted=True),
        ),
        mock.patch(
            "yoke_core.domain.deployment_qa_stage_materialization"
            ".materialize_deployment_qa_stage"
        ),
        mock.patch.object(
            dispatch_mod,
            "notify_qa_stage_result",
            side_effect=RuntimeError("inbox unavailable"),
        ),
    ):
        rc, _diag = materialize_and_gate_deployment_qa_stage(
            test_db, stage, run_id="run-report-5"
        )

    assert rc == 0
    assert "could not report" in capsys.readouterr().out
