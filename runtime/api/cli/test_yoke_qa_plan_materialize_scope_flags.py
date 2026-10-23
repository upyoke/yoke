"""`yoke qa plan materialize` can reach the stage binding the handler accepts.

The handler has always routed a deployment-run materialization to the scoped
path when the payload named a stage, but the adapter exposed no flag for it,
so every CLI materialization produced an unbound row — one the item-scoped
stage does not count.
"""

from __future__ import annotations

from unittest.mock import patch
import pytest
from runtime.api.cli.test_yoke_operations_cli_qa import (
    _run,
    _stub_ok,
    _CAPTURED_REQUESTS,
)

from yoke_cli.commands.adapters.qa_execution_subjects import (
    qa_plan_materialize_for_item,
)

RUN_ID = "run-20260101-004"


def _dispatch_kwargs(args: list[str]) -> dict:
    with patch(
        "yoke_cli.commands.adapters.qa_execution_subjects.dispatch_and_emit",
        return_value=0,
    ) as dispatched:
        assert qa_plan_materialize_for_item(args) == 0
    return dispatched.call_args.kwargs


def test_the_stage_and_item_reach_the_handler() -> None:
    kwargs = _dispatch_kwargs(
        [
            "--stage",
            "item-qa",
            "--item",
            "PREFIX-7",
            "--plan",
            "release-boundary-qa",
            "--project",
            "yoke",
        ]
    )

    assert kwargs["payload"]["deployment_stage"] == "item-qa"
    assert kwargs["target"].kind == "item"
    assert kwargs["target"].public_ref == "PREFIX-7"
    assert "deployment_member" not in kwargs["payload"]


def test_a_member_without_its_stage_is_refused() -> None:
    args = [
        "--deployment-run-id",
        RUN_ID,
        "--member",
        "PREFIX-7",
        "--plan",
        "release-boundary-qa",
        "--project",
        "yoke",
    ]

    assert qa_plan_materialize_for_item(args) == 2


def test_a_stage_without_a_deployment_run_is_refused() -> None:
    args = ["--item", "PREFIX-7", "--transition", "release", "--stage", "item-qa"]

    assert qa_plan_materialize_for_item(args) == 2


def test_item_rematerialize_refuses_plan_filter(capsys) -> None:
    from yoke_cli.commands.adapters.qa_execution_subjects import qa_plan_rematerialize

    with patch(
        "yoke_cli.commands.adapters.qa_execution_subjects.dispatch_and_emit"
    ) as dispatch:
        assert (
            qa_plan_rematerialize(
                [
                    "--item",
                    "PREFIX-7",
                    "--transition",
                    "release",
                    "--plan",
                    "smoke",
                ]
            )
            == 2
        )
    dispatch.assert_not_called()
    assert "item_plan_filter_unsupported" in capsys.readouterr().err


class TestQaDeploymentPlanMaterialize:
    @pytest.fixture(autouse=True)
    def reset_captured(self):
        _CAPTURED_REQUESTS.clear()

    def test_dispatches_real_deployment_run_subject(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "plan",
            "materialize",
            "--deployment-run-id",
            "run-20260728-901",
            "--plan",
            "installer-campaign",
            "--project",
            "yoke",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "qa.plan.materialize"
        assert req.target.kind == "deployment_run"
        assert req.target.deployment_run_id == "run-20260728-901"
        assert req.target.project_id == "yoke"
        assert req.payload == {
            "transition_id": None,
            "plan": "installer-campaign",
            "project": "yoke",
            "deployment_stage": None,
        }

    def test_replaces_declares_each_failed_requirement(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "plan",
            "materialize",
            "--deployment-run-id",
            "run-20260728-901",
            "--stage",
            "run-visual-qa",
            "--plan",
            "corrected",
            "--project",
            "yoke",
            "--replaces",
            "desktop=32796",
            "--replaces",
            "narrow=32797",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload["replacements"] == [
            {"case_key": "desktop", "requirement_id": 32796},
            {"case_key": "narrow", "requirement_id": 32797},
        ]

    def test_requires_named_plan_and_project(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "plan",
            "materialize",
            "--deployment-run-id",
            "run-20260728-901",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []
