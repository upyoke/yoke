"""Execution context performs one composition pass and preserves its enrollment."""

from contextlib import nullcontext
from unittest.mock import patch
import pytest
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import deployment_run_execution as execution
from yoke_core.domain.deployment_run_pipe_format import pipe_row
from yoke_core.domain.deployment_runs_schema import RUN_FIELDS
from yoke_core.domain.deployment_run_carried_work import require_bound_project_coverage


def test_execution_context_composes_once_and_returns_its_enrollment():
    values = {
        "id": "run-once",
        "project": "project",
        "flow": "flow",
        "release_lineage": "a" * 40,
    }
    raw = pipe_row([values.get(field, "") for field in RUN_FIELDS])

    def compose(run_id, *, composition_result):
        assert run_id == "run-once"
        composition_result["enrolled"] = ["item-ref"]
        return True, "OK"

    request = FunctionCallRequest(
        function="deployment_runs.execution.context",
        actor=ActorContext(session_id="session"),
        target=TargetRef(kind="workflow_run", workflow_run_id="run-once"),
    )
    with (
        patch.object(execution, "_require_execution_lock", return_value=None),
        patch.object(execution, "_record_bound_sources", return_value={}),
        patch.object(execution, "_member_rows", return_value=[]),
        patch(
            "yoke_core.domain.deployment_runs_validation.cmd_validate_composition",
            side_effect=compose,
        ) as composition,
        patch("yoke_core.domain.deployment_runs_crud_query.cmd_get", return_value=raw),
        patch(
            "yoke_core.domain.db_helpers.connect", return_value=nullcontext(object())
        ),
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
    assert result.primary_success
    assert result.result_payload["enrolled_carried_items"] == ["item-ref"]
    composition.assert_called_once()


def test_a_cached_composition_missing_a_bound_project_refuses():
    with pytest.raises(ValueError, match="Cancel this run and create a new one"):
        require_bound_project_coverage(
            "run-stale",
            {"bound_projects": []},
            {"schema": 1, "projects": [{"project_id": 3, "commit_sha": "a" * 40}]},
        )
