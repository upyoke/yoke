"""CLI coverage for the typed QA plan reviewer handoff."""

from __future__ import annotations

import io
import json
import sys
from unittest import mock

from yoke_core.domain import qa_plan_execution_cli, qa_plan_review_cli
from yoke_core.domain.qa_plan_review import _dispatch_contract
from yoke_core.domain.qa_review_verdict_modes import (
    ALL_REVIEW_VERDICTS,
    CONCLUSIVE_REVIEW_VERDICTS,
    allowed_review_verdicts,
    inconclusive_verdict_guidance,
    verdict_enum_text,
)


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
                        "yoke qa plan review-submit --item 42 "
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
    assert "QA capture complete; independent review pending, not a pass" in output.err
    assert "Dispatch the returned typed reviewer contract now" in output.err


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
                "--item",
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
                "verdict": "undetermined",
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
                "--item",
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


class TestSubmitHelpNamesTheContract:
    """A reviewer must be able to read the schema before composing a batch.

    Discovering the stdin shape or the verdict vocabulary from a rejection
    costs the whole review that produced it.
    """

    def _help_text(self, capsys) -> str:
        try:
            qa_plan_review_cli.run(["--help"])
        except SystemExit:
            pass
        return capsys.readouterr().out

    def test_help_shows_the_stdin_shape(self, capsys) -> None:
        text = self._help_text(capsys)
        assert '"verdicts"' in text
        assert '"requirement_id"' in text
        assert '"rationale"' in text

    def test_help_lists_every_verdict_the_column_allows(self, capsys) -> None:
        text = self._help_text(capsys)
        assert verdict_enum_text(ALL_REVIEW_VERDICTS) in text

    def test_help_sends_the_reader_to_the_stage_narrowed_set(self, capsys) -> None:
        text = self._help_text(capsys)
        assert "this stage may accept fewer" in text
        assert "dispatch.result_schema" in text

    def test_help_says_the_batch_is_complete_or_refused(self, capsys) -> None:
        assert "A partial batch is refused" in self._help_text(capsys)


class TestDispatchOffersOnlyWhatTheStageAccepts:
    """An agent_only stage refuses undetermined, so it must not offer it."""

    def test_agent_only_mode_drops_the_inconclusive_verdict(self) -> None:
        assert allowed_review_verdicts("agent_only") == CONCLUSIVE_REVIEW_VERDICTS

    def test_human_modes_keep_it(self) -> None:
        for mode in ("human_if_unsure", "required_human"):
            assert allowed_review_verdicts(mode) == ALL_REVIEW_VERDICTS

    def test_no_stage_keeps_it(self) -> None:
        assert allowed_review_verdicts(None) == ALL_REVIEW_VERDICTS

    def test_agent_only_guidance_names_the_conclusive_answer(self) -> None:
        guidance = inconclusive_verdict_guidance(CONCLUSIVE_REVIEW_VERDICTS)
        assert "undetermined is not submittable here" in guidance
        assert "pass|fail" in guidance
        assert "fail it and name in the rationale what was missing" in guidance

    def test_escalating_guidance_still_explains_the_cost(self) -> None:
        guidance = inconclusive_verdict_guidance(ALL_REVIEW_VERDICTS)
        assert "spends an owner/operator review" in guidance

    def test_dispatch_contract_carries_the_narrowed_enum(self) -> None:
        bundle = {
            "bundle_id": "bundle-1",
            "bundle_digest": "a" * 64,
            "execution_id": "execution-1",
            "roster_digest": "d",
            "execution_target": {"environment": {"name": "production"}},
            "execution_target_digest": "b" * 64,
            "state": "pending",
            "subject": {"item_id": 42, "deployment_run_id": None},
            "cases": [{"requirement_id": 41, "capture_runner": "browser_substrate"}],
        }
        dispatch = _dispatch_contract(
            bundle, allowed_verdicts=CONCLUSIVE_REVIEW_VERDICTS
        )
        schema_verdict = dispatch["result_schema"]["verdicts"][0]["verdict"]
        assert schema_verdict == "pass|fail"
        assert "undetermined is not submittable here" in dispatch["prompt"]
