"""Execution context performs one composition pass and preserves its enrollment."""

from contextlib import nullcontext
from typing import Any
from unittest.mock import Mock, patch
import pytest
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import deployment_run_execution as execution
from yoke_core.domain.deployment_run_carried_work import require_bound_project_coverage


def _context(*, frozen: bool, compose: Any, frozen_verdict: Any):
    """Run the execution context with every read but composition stubbed."""
    values = {
        "id": "run-once",
        "project": "project",
        "flow": "flow",
        "release_lineage": "a" * 40,
    }
    conn = Mock()
    request = FunctionCallRequest(
        function="deployment_runs.execution.context",
        actor=ActorContext(session_id="session"),
        target=TargetRef(kind="workflow_run", workflow_run_id="run-once"),
    )
    with (
        patch.object(execution, "require_run_driver", return_value=None),
        patch.object(execution, "_record_bound_sources", return_value={}),
        patch.object(execution, "_member_rows", return_value=[]),
        patch(
            "yoke_core.domain.deployment_run_composition_guard.has_frozen_composition",
            return_value=frozen,
        ),
        patch(
            "yoke_core.domain.deployment_runs_validation.cmd_validate_composition",
            side_effect=compose,
        ) as composition,
        patch(
            "yoke_core.domain.deployment_run_reopened_members."
            "frozen_composition_verdict",
            side_effect=frozen_verdict,
        ) as frozen_check,
        patch(
            "yoke_core.domain.deployment_runs_crud_query.get_run", return_value=values
        ),
        patch("yoke_core.domain.db_helpers.connect", return_value=nullcontext(conn)),
        patch("yoke_core.domain.flow.cmd_stages", return_value="[]"),
        patch(
            "yoke_core.domain.deployment_run_contained_items.candidate_containment_basis",
            return_value={},
        ),
        patch(
            "yoke_core.domain.deployment_target_identity_config.run_target_identity",
            return_value={},
        ),
        patch("yoke_core.domain.project_identity.resolve_project_id", return_value=1),
    ):
        result = execution.handle_deployment_execution_context(request)
    return result, conn, composition, frozen_check


def _unexpected(*_args: Any, **_kwargs: Any):
    raise AssertionError("this composition path must not run")


def test_execution_context_composes_once_and_returns_its_enrollment():
    def compose(run_id, *, composition_result, connection):
        assert run_id == "run-once"
        composition_result["enrolled"] = ["item-ref"]
        return True, "OK"

    result, conn, composition, _ = _context(
        frozen=False, compose=compose, frozen_verdict=_unexpected
    )
    assert result.primary_success
    assert result.result_payload["enrolled_carried_items"] == ["item-ref"]
    composition.assert_called_once()
    assert composition.call_args.kwargs["connection"] is conn
    conn.commit.assert_called_once()


def test_a_frozen_run_redrive_judges_only_members_that_can_change():
    result, conn, composition, frozen_check = _context(
        frozen=True,
        compose=_unexpected,
        frozen_verdict=lambda *_args: (True, "OK"),
    )
    assert result.primary_success
    assert result.result_payload["enrolled_carried_items"] == []
    composition.assert_not_called()
    frozen_check.assert_called_once_with(conn, "run-once")
    conn.commit.assert_called_once()


def test_a_frozen_run_redrive_refuses_a_member_it_cannot_judge():
    refusal = "FAIL: Composition validation failed:\nItems not delivery-ready"
    result, conn, _, _ = _context(
        frozen=True,
        compose=_unexpected,
        frozen_verdict=lambda *_args: (False, refusal),
    )
    assert not result.primary_success
    assert result.error.code == "composition_invalid"
    assert refusal in result.error.message
    conn.rollback.assert_called_once()


def test_a_cached_composition_missing_a_bound_project_refuses():
    with pytest.raises(ValueError, match="Cancel this run and create a new one"):
        require_bound_project_coverage(
            "run-stale",
            {"bound_projects": []},
            {"schema": 1, "projects": [{"project_id": 3, "commit_sha": "a" * 40}]},
        )
