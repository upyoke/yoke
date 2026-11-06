"""Response loss preserves the existing dispatch attempt and its correlation."""

from unittest import mock
import pytest
from runtime.api.domain.deploy_pipeline_stage_receipt_test_support import (
    _BASE_KWARGS,
    _control_plane_mocks,
    _qa_stage,
    _stage,
)
from yoke_core.domain import deploy_pipeline_stage_receipt as receipts
from yoke_core.domain.deploy_pipeline_unknown_outcome import DeploymentOutcomeUnknown


def test_lost_preparation_response_keeps_stage_receipt_pending():
    stage = _stage("deploy-stage", "health-check")
    allocate, complete, latest = _control_plane_mocks(
        latest={"status": "pending", "correlation_id": "existing-attempt"}
    )
    lost = DeploymentOutcomeUnknown(
        "run-receipt-wrapper", "prepare", "request", "response lost"
    )
    with (
        mock.patch.object(receipts.control_plane, "allocate_stage_receipt", allocate),
        mock.patch.object(receipts.control_plane, "complete_stage_receipt", complete),
        mock.patch.object(receipts.control_plane, "latest_stage_receipt", latest),
        mock.patch.object(
            receipts, "_dispatch_step_runner", side_effect=lost
        ) as dispatch,
    ):
        with pytest.raises(DeploymentOutcomeUnknown):
            receipts.dispatch_step_runner_with_receipt(
                stage, stages=[stage, _qa_stage("deploy-stage")], **_BASE_KWARGS
            )
    assert allocate.call_args.kwargs["correlation_id"] == "existing-attempt"
    dispatch.assert_called_once()
    complete.assert_not_called()
