"""CLI envelopes for QA methods, plans, attachments, and evidence reads."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def _run(*argv: str, stdin: str = "") -> tuple[int, FunctionCallRequest]:
    captured: list[FunctionCallRequest] = []

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            request_id=request.request_id,
            version=request.version,
            result={},
        )

    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "qa-catalog-test"}),
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=dispatch,
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        patch("sys.stdin", io.StringIO(stdin)),
        redirect_stdout(io.StringIO()),
        redirect_stderr(io.StringIO()),
    ):
        result = cli_main(list(argv))
    assert captured
    return result, captured[-1]


def test_method_and_plan_reads_keep_project_context_in_payload() -> None:
    result, request = _run(
        "qa",
        "method",
        "get",
        "browser-check",
        "--project",
        "yoke",
    )
    assert result == 0
    assert request.function == "qa.method.get"
    assert request.target.kind == "global"
    assert request.payload == {
        "project": "yoke",
        "method_id": "browser-check",
    }

    result, request = _run(
        "qa",
        "plan",
        "get",
        "17",
        "--project",
        "yoke",
    )
    assert result == 0
    assert request.function == "qa.plan.get"
    assert request.payload == {"project": "yoke", "plan_id": 17}

    result, request = _run(
        "qa",
        "plan",
        "get",
        "17",
        "--project",
        "yoke",
        "--deployment-run-id",
        "run-20260728-906",
    )
    assert result == 0
    assert request.payload == {
        "project": "yoke",
        "plan_id": 17,
        "deployment_run_id": "run-20260728-906",
    }

    result, request = _run(
        "qa",
        "activity",
        "list",
        "--project",
        "yoke",
        "--deployment-run-id",
        "run-20260728-906",
    )
    assert result == 0
    assert request.payload == {
        "project": "yoke",
        "deployment_run_id": "run-20260728-906",
        "limit": 100,
    }


def test_project_method_register_maps_the_complete_contract() -> None:
    result, request = _run(
        "qa",
        "project-method",
        "register",
        "--project",
        "yoke",
        "--slug",
        "accessibility-scan",
        "--name",
        "Accessibility scan",
        "--description",
        "Exercise the rendered page.",
        "--runner",
        "browser_substrate",
        "--verdict-path",
        "agent",
        "--verdict-contract",
        "Report pass or fail.",
        "--evidence-contract",
        "Attach a screenshot.",
        "--concurrency-mode",
        "serial",
        "--success-policy-params",
        '{"minimum_score": 90}',
    )
    assert result == 0
    assert request.function == "qa.project_method.register"
    assert request.target.kind == "global"
    assert request.payload == {
        "project": "yoke",
        "slug": "accessibility-scan",
        "name": "Accessibility scan",
        "description": "Exercise the rendered page.",
        "runner_id": "browser_substrate",
        "verdict_path": "agent",
        "verdict_contract": "Report pass or fail.",
        "evidence_contract": "Attach a screenshot.",
        "concurrency_mode": "serial",
        "success_policy_params": {"minimum_score": 90},
    }


def test_case_replace_reads_a_json_array_from_stdin() -> None:
    result, request = _run(
        "qa",
        "plan-cases",
        "replace",
        "--project",
        "yoke",
        "--plan-id",
        "17",
        "--stdin",
        stdin=(
            '[{"case_key":"full","position":1,"method_id":"command",'
            '"instructions":"Run it","expected_outcome":"It passes"}]'
        ),
    )
    assert result == 0
    assert request.function == "qa.plan_cases.replace"
    assert request.payload["project"] == "yoke"
    assert request.payload["plan_id"] == 17
    assert request.payload["cases"][0]["case_key"] == "full"


def test_project_default_and_item_attachment_use_distinct_targets() -> None:
    result, default_request = _run(
        "qa",
        "project-default",
        "set",
        "--project",
        "yoke",
        "--plan-id",
        "17",
        "--workflow",
        "issue",
        "--transition",
        "reviewed-implementation",
    )
    assert result == 0
    assert default_request.function == "qa.project_default.set"
    assert default_request.target.kind == "global"

    result, unset_request = _run(
        "qa",
        "project-default",
        "unset",
        "--project",
        "yoke",
        "--plan-id",
        "17",
        "--workflow",
        "issue",
        "--transition",
        "reviewed-implementation",
    )
    assert result == 0
    assert unset_request.function == "qa.project_default.unset"
    assert unset_request.target.kind == "global"
    assert unset_request.payload["transition_id"] == "reviewed-implementation"

    result, item_request = _run(
        "qa",
        "item-plan",
        "attach",
        "--project",
        "yoke",
        "--item",
        TEST_ITEM_REF,
        "--plan-id",
        "17",
        "--transition",
        "reviewed-implementation",
    )
    assert result == 0
    assert item_request.function == "qa.item_plan.attach"
    assert item_request.target.kind == "item"
    assert item_request.target.item_ref == TEST_ITEM_REF
    assert item_request.payload["plan_id"] == 17


def test_artifact_read_uses_requirement_target() -> None:
    result, request = _run(
        "qa",
        "artifact",
        "read",
        "--requirement-id",
        "31",
        "--artifact-id",
        "4",
    )
    assert result == 0
    assert request.function == "qa.artifact.read"
    assert request.target.kind == "qa_requirement"
    assert request.target.qa_requirement_id == 31
    assert request.payload == {"artifact_id": 4}


def test_case_replace_rejects_non_array_json_without_dispatch() -> None:
    with (
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        patch("sys.stdin", io.StringIO('{"not":"a case list"}')),
        redirect_stdout(io.StringIO()),
        redirect_stderr(io.StringIO()),
    ):
        result = cli_main(
            [
                "qa",
                "plan-cases",
                "replace",
                "--project",
                "yoke",
                "--plan-id",
                "17",
                "--stdin",
            ]
        )
    assert result == 2
