"""CLI coverage for the typed QA plan reviewer handoff."""

from __future__ import annotations

import io
import json
import sys
from unittest import mock

from yoke_core.domain import qa_plan_execution_cli, qa_plan_review_cli


def test_plan_engine_cli_requires_environment_bound_agent_review_dispatch(
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_ENV", "external-project-qa")
    with mock.patch.object(
        qa_plan_execution_cli,
        "execute_plan",
        return_value={
            "item_id": 42,
            "transition_id": "implemented",
            "state": "awaiting_agent_review",
            "review_bundle": {
                "dispatch": {
                    "subagent_type": "yoke-tester",
                    "authority": {
                        "state": "bound",
                        "environment": "quality",
                        "execution_target_digest": "b" * 64,
                    },
                    "artifact_read_commands": [
                        "yoke qa artifact read --requirement-id 41 --artifact-id 91"
                    ],
                    "prompt": "Review the exact immutable bundle.",
                    "submit_command": (
                        "yoke qa plan review-submit --item-id 42 "
                        "--execution-id execution-1 --bundle-id bundle-1 "
                        f"--bundle-digest {'a' * 64} --stdin"
                    ),
                },
            },
        },
    ):
        code = qa_plan_execution_cli.run(
            [
                "--item",
                "YOK-42",
                "--transition",
                "implemented",
            ]
        )

    output = capsys.readouterr()
    assert code == qa_plan_execution_cli.AGENT_REVIEW_REQUIRED_EXIT
    result = json.loads(output.out)
    assert result["state"] == "awaiting_agent_review"
    dispatch = result["review_bundle"]["dispatch"]
    assert dispatch["authority"]["connection_env"] == "external-project-qa"
    assert dispatch["artifact_read_commands"] == [
        "yoke --env external-project-qa qa artifact read "
        "--requirement-id 41 --artifact-id 91"
    ]
    assert dispatch["submit_command"].startswith(
        "yoke --env external-project-qa qa plan review-submit"
    )
    assert "do not use the ambient connection" in dispatch["prompt"]
    assert "dispatch the returned typed reviewer contract now" in output.err


def test_review_submit_cli_sends_complete_stdin_batch(capsys) -> None:
    payload = {
        "verdicts": [
            {
                "requirement_id": 41,
                "verdict": "pass",
                "rationale": "The frame matches the expected outcome.",
            }
        ]
    }
    with (
        mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
        mock.patch.object(
            qa_plan_review_cli,
            "_call_plan_function",
            return_value={
                "execution_id": "execution-1",
                "bundle_id": "bundle-1",
                "state": "passed",
                "verdicts": payload["verdicts"],
            },
        ) as submit,
    ):
        code = qa_plan_review_cli.run(
            [
                "--item-id",
                "42",
                "--execution-id",
                "execution-1",
                "--bundle-id",
                "bundle-1",
                "--bundle-digest",
                "a" * 64,
                "--stdin",
                "--session-id",
                "reviewer-session",
            ]
        )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["state"] == "passed"
    assert submit.call_args.kwargs["function_id"] == "qa.plan_review.submit"
    assert submit.call_args.kwargs["payload"]["verdicts"] == payload["verdicts"]


def test_review_submit_exits_zero_when_verdicts_persisted_on_needs_review(
    capsys,
) -> None:
    payload = {
        "verdicts": [
            {
                "requirement_id": 41,
                "verdict": "inconclusive",
                "rationale": "Needs a human look.",
            }
        ]
    }
    with (
        mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
        mock.patch.object(
            qa_plan_review_cli,
            "_call_plan_function",
            return_value={
                "execution_id": "execution-1",
                "bundle_id": "bundle-1",
                "state": "needs_review",
                "submission": "persisted",
                "verdicts": payload["verdicts"],
            },
        ) as submit,
    ):
        code = qa_plan_review_cli.run(
            [
                "--item-id",
                "42",
                "--execution-id",
                "execution-1",
                "--bundle-id",
                "bundle-1",
                "--bundle-digest",
                "a" * 64,
                "--stdin",
            ]
        )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["submission"] == "persisted"
    assert submit.call_args.kwargs["function_id"] == "qa.plan_review.submit"
    assert submit.call_args.kwargs["payload"]["verdicts"] == payload["verdicts"]
