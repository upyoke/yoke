"""Containment refresh answers to the run driver; it has no membership or QA effects."""

from contextlib import nullcontext
from unittest.mock import patch
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    ActorContext,
    TargetRef,
)
from yoke_core.domain.handlers import deployment_containment_basis as handler


def _request():
    return FunctionCallRequest(
        function=handler.FUNCTION_ID,
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind="workflow_run", workflow_run_id="run-refresh"),
        payload={},
    )


def test_basis_refresh_reads_only_containment_and_honors_driver():
    conn = object()
    basis = {"basis_digest": "new"}
    with (
        patch.object(handler, "require_run_driver", return_value=None) as driver,
        patch("yoke_core.domain.db_helpers.connect", return_value=nullcontext(conn)),
        patch(
            "yoke_core.domain.deployment_run_contained_items.candidate_containment_basis",
            return_value=basis,
        ) as read,
        patch(
            "yoke_core.domain.deployment_runs_validation.cmd_validate_composition"
        ) as compose,
    ):
        result = handler.handle(_request())
    assert result.primary_success
    assert result.result_payload["candidate_containment_basis"] == basis
    driver.assert_called_once()
    read.assert_called_once_with(conn, "run-refresh")
    compose.assert_not_called()


def test_driver_refusal_does_not_read_basis():
    refusal = handler.error("run_driven_elsewhere", "Another session drives this run")
    with (
        patch.object(handler, "require_run_driver", return_value=refusal),
        patch("yoke_core.domain.db_helpers.connect") as connect,
    ):
        assert handler.handle(_request()) is refusal
    connect.assert_not_called()
