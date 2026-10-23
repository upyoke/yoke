"""A member's QA configuration refusal holds that member; it never fails the run.

A saved plan the gate refuses is fixable configuration. The stage records a
``qa_configuration_refused`` blocker for that member and keeps waiting, so
other members still settle. The driver does not exit for it. Any other stage
error still fails the stage as before.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.domain.test_deploy_pipeline_scoped_qa_reporting import (  # noqa: F401
    awaiting_driver,
    scoped_run,
)
from runtime.api.domain.test_deployment_qa_stage_dispatch_close_order import (
    MEMBER_SEQUENCES,
    PROJECT_SLUG,
    PUBLIC_PREFIX,
    RUN_ID,
    SETTLED_MEMBER,
    STAGE,
    WAITING_MEMBER,
    _Conn,
    _status,
)
from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import deploy_pipeline as pipeline
from yoke_core.domain import deployment_qa_stage_dispatch as dispatch
from yoke_core.domain import deployment_qa_stage_gate as gate
from yoke_core.domain.deploy_pipeline_qa_wait import AWAITING_SCOPED_QA
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


def test_member_configuration_refusal_holds_that_member_while_others_settle() -> None:
    """The refusing member is first, so a later member still has to settle."""

    def gated(conn, *, member_item_id, **kw):
        if member_item_id == SETTLED_MEMBER:
            raise QaPlanError(SNAPSHOT_MISSING)
        return {"accepted": True, "reasons": [], "outcome": "discharged"}

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

    refused = format_item_ref(
        PROJECT_SLUG, PUBLIC_PREFIX, MEMBER_SEQUENCES[SETTLED_MEMBER]
    )
    assert code == AWAITING_SCOPED_QA
    assert message.startswith(
        f"member {refused}: qa_configuration_refused: {SNAPSHOT_MISSING}"
    )
    assert f"{refused} stays held at stage 'item-qa'" in message
    assert f"Run {RUN_ID} stays executing" in message
    assert "recorded QA results are kept" in message
    assert f"`yoke watch deploy -- {RUN_ID}`" in message
    assert closed == [WAITING_MEMBER]


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


def test_driver_still_fails_the_run_on_a_real_stage_failure(
    stage_failures, monkeypatch
):
    run_id, failed = stage_failures
    monkeypatch.setattr(
        pipeline, "dispatch_until_qa_resolves", lambda *a, **k: (1, "QA failed")
    )

    assert pipeline.run_pipeline(run_id, sd="/tmp/sd") == pipeline.EXIT_STAGE_FAILED
    assert [(f["exit_code"], f["diagnostic"]) for f in failed] == [(1, "QA failed")]
