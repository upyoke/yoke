"""CLI coverage for the typed QA plan reviewer handoff."""

from __future__ import annotations

import io
import json
import sys
from unittest import mock

from yoke_core.domain import qa_plan_execution_cli, qa_plan_review_cli


def test_plan_engine_cli_requires_immediate_agent_review_dispatch(capsys) -> None:
    with mock.patch.object(
        qa_plan_execution_cli,
        "execute_plan",
        return_value={
            "item_id": 42,
            "transition_id": "implemented",
            "state": "awaiting_agent_review",
            "review_bundle": {
                "dispatch": {"subagent_type": "yoke-tester"},
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
    assert json.loads(output.out)["state"] == "awaiting_agent_review"
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
