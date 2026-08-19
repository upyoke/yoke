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


def _install_prepare_fakes(monkeypatch, worktree_path):
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
        "Outcome",
        (),
        {
            "ok": True,
            "worktree_path": str(worktree_path),
            "to_envelope": lambda self: {"ok": True},
        },
    )()
    monkeypatch.setattr(preflight, "run_preflight", lambda **_kwargs: outcome)


def test_successful_yoke_prepare_receipt_names_run_surfaces(
    monkeypatch,
    capsys,
    tmp_path,
):
    (tmp_path / "packages/yoke-core/src/yoke_core").mkdir(parents=True)
    _install_prepare_fakes(monkeypatch, tmp_path)

    assert preflight.run(["YOK-7", "--workflow", "dash"]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["run_recipes"] == {
        "pytest": PYTEST_RUN_RECIPE,
        "source": SOURCE_RUN_RECIPE,
        "install_bundle_sync": INSTALL_BUNDLE_SYNC_RECIPE,
    }
    assert "source_dev_recipe" not in receipt


def test_external_project_prepare_receipt_omits_yoke_source_recipe(
    monkeypatch,
    capsys,
    tmp_path,
):
    _install_prepare_fakes(monkeypatch, tmp_path)

    assert preflight.run(["YOK-7", "--workflow", "dash"]) == 0

    assert json.loads(capsys.readouterr().out)["run_recipes"] == {
        "pytest": PYTEST_RUN_RECIPE,
        "install_bundle_sync": INSTALL_BUNDLE_SYNC_RECIPE,
    }
