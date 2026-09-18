"""`yoke qa plan materialize` can reach the stage binding the handler accepts.

The handler has always routed a deployment-run materialization to the scoped
path when the payload named a stage, but the adapter exposed no flag for it,
so every CLI materialization produced an unbound row — one the item-scoped
stage does not count.
"""

from __future__ import annotations

from unittest.mock import patch

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


def test_the_stage_and_member_reach_the_handler_payload() -> None:
    kwargs = _dispatch_kwargs(
        [
            "--deployment-run-id",
            RUN_ID,
            "--stage",
            "item-qa",
            "--member",
            "PREFIX-7",
            "--plan",
            "release-boundary-qa",
            "--project",
            "yoke",
        ]
    )

    assert kwargs["payload"]["deployment_stage"] == "item-qa"
    assert kwargs["payload"]["deployment_member"] == "PREFIX-7"


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
