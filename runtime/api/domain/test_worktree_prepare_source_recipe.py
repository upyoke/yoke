"""The worktree receipt teaches the sanctioned claimed-lane run surfaces."""

from __future__ import annotations

import json

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import direct_workflow_worktree_preflight as preflight
from yoke_core.tools._source_pythonpath import (
    INSTALL_BUNDLE_SYNC_RECIPE,
    PYTEST_RUN_RECIPE,
    SOURCE_RUN_RECIPE,
)


def _response(function: str, result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function=function, version="v1", result=result,
    )


def test_successful_prepare_receipt_names_run_surfaces(monkeypatch, capsys):
    def _dispatch(*, function_id, **_kwargs):
        if function_id == "items.detail.get":
            return _response(
                function_id,
                {"item": {"id": 7, "workflow": {"id": "dash"}}},
            )
        if function_id == "direct_workflow.conflict_survey.status":
            return _response(
                function_id,
                {"found": True, "clear": True, "touch_paths": ["src/x.py"]},
            )
        raise AssertionError(function_id)

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        _dispatch,
    )
    outcome = type(
        "Outcome", (), {"ok": True, "to_envelope": lambda self: {"ok": True}},
    )()
    monkeypatch.setattr(preflight, "run_preflight", lambda **_kwargs: outcome)

    assert preflight.run(["YOK-7", "--workflow", "dash"]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["run_recipes"] == {
        "pytest": PYTEST_RUN_RECIPE,
        "source": SOURCE_RUN_RECIPE,
        "install_bundle_sync": INSTALL_BUNDLE_SYNC_RECIPE,
    }
    assert "source_dev_recipe" not in receipt
