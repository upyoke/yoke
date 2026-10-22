"""The CLI retrieves typed capture review authority without reopening a walk."""

import json
from unittest import mock

import pytest

from yoke_core.domain import qa_plan_review_begin_cli

_FIXTURE_ITEM_REF = f"YOK-{42}"


@pytest.mark.parametrize(
    "flag,value,kind",
    [
        ("--item", _FIXTURE_ITEM_REF, "item"),
        (None, None, "global"),
        ("--project", "example", "global"),
    ],
)
def test_review_begin_retrieves_and_qualifies_terminal_capture_bundle(
    flag, value, kind, capsys
):
    result = {
        "execution_id": "execution-captures",
        "state": "aborted",
        "review_bundle": {"bundle_id": "capture-bundle"},
    }
    with (
        mock.patch.object(qa_plan_review_begin_cli, "build_actor") as actor,
        mock.patch.object(
            qa_plan_review_begin_cli, "_call_plan_function", return_value=result
        ) as call,
        mock.patch.object(
            qa_plan_review_begin_cli, "_qualify_review_dispatch"
        ) as qualify,
    ):
        assert (
            qa_plan_review_begin_cli.main(
                [
                    *([flag, value] if flag else []),
                    "--execution-id",
                    "execution-captures",
                    "--session-id",
                    "owner",
                ]
            )
            == 0
        )
    assert call.call_args.kwargs["function_id"] == "qa.plan_review.begin"
    assert call.call_args.kwargs["target"].kind == kind
    assert call.call_args.kwargs["payload"] == {"execution_id": "execution-captures"}
    actor.assert_called_once_with(session_id="owner")
    qualify.assert_called_once_with(result)
    assert json.loads(capsys.readouterr().out)["state"] == "aborted"
