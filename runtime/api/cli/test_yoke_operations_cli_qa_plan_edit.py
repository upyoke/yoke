"""CLI contract tests for interactive QA plan editing."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from runtime.api.cli.qa_plan_edit_cli_test_support import (
    CONTEXT_ARGS,
    EDIT_ARGS,
    PLAN,
    run_cli,
)
from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
)


def test_edit_opens_only_authorable_fields_and_dispatches_full_cas() -> None:
    requests: list[FunctionCallRequest] = []
    editor_path: Path | None = None

    def editor(argv, *, check):
        nonlocal editor_path
        assert check is False
        assert argv[:2] == ["code", "--wait"]
        editor_path = Path(argv[-1])
        document = json.loads(editor_path.read_text(encoding="utf-8"))
        assert set(document) == {
            "slug",
            "name",
            "description",
            "success_policy_id",
            "success_policy_params",
            "target_environment",
            "cases",
        }
        assert set(document["cases"][0]) == {
            "case_key",
            "position",
            "method_id",
            "instructions",
            "expected_outcome",
            "method_config",
            "success_policy_id",
            "success_policy_params",
            "host_baselines",
            "entry_surface",
            "required_completion",
        }
        document["name"] = "Release gate"
        editor_path.write_text(
            json.dumps(document),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0)

    result, _stdout, stderr = run_cli(
        requests,
        editor,
        *EDIT_ARGS,
        "--editor",
        "code --wait",
    )
    assert result == 0
    assert stderr == ""
    assert editor_path is not None
    assert not editor_path.exists()
    assert [request.function for request in requests] == [
        "qa.plan.list",
        "qa.plan.get",
        "qa.plan.edit",
    ]
    assert {request.actor.session_id for request in requests} == {"qa-plan-edit-test"}
    saved = requests[-1]
    assert saved.target.kind == "global"
    assert saved.payload["project"] == "yoke"
    assert saved.payload["slug"] == "release-readiness"
    assert saved.payload["name"] == "Release gate"
    assert saved.payload["target_environment"] is None
    assert saved.payload["base_updated_at"] == PLAN["updated_at"]
    assert saved.payload["cases"][0]["case_key"] == "backend-suite"


def test_checkout_project_id_is_canonicalized_from_the_list_row() -> None:
    requests: list[FunctionCallRequest] = []

    def editor(argv, *, check):
        return subprocess.CompletedProcess(argv, 0)

    with patch(
        "yoke_cli.commands.adapters.qa_plan_edit.client_project_context",
        return_value="1",
    ):
        result, _stdout, _stderr = run_cli(
            requests,
            editor,
            *CONTEXT_ARGS,
        )
    assert result == 0
    assert requests[0].payload["project"] == "1"
    assert requests[1].payload["project"] == "yoke"
    assert requests[2].payload["project"] == "yoke"


def test_missing_checkout_project_context_refuses_before_dispatch() -> None:
    requests: list[FunctionCallRequest] = []

    def editor(_argv, *, check):
        raise AssertionError(f"editor must not run (check={check})")

    with patch(
        "yoke_cli.commands.adapters.qa_plan_edit.client_project_context",
        return_value=None,
    ):
        result, _stdout, _stderr = run_cli(
            requests,
            editor,
            *CONTEXT_ARGS,
        )
    assert result == 2
    assert requests == []


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        ("start", "editor_start_failed"),
        ("exit", "editor_exit_failed"),
        ("json", "invalid_editor_document"),
    ],
)
def test_json_mode_wraps_local_editor_failures(
    failure: str,
    code: str,
) -> None:
    requests: list[FunctionCallRequest] = []
    editor_path: Path | None = None

    def editor(argv, *, check):
        nonlocal editor_path
        editor_path = Path(argv[-1])
        if failure == "start":
            raise OSError("editor executable missing")
        if failure == "exit":
            return subprocess.CompletedProcess(argv, 7)
        editor_path.write_text("{not json", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)

    result, stdout, stderr = run_cli(
        requests,
        editor,
        *EDIT_ARGS,
        "--json",
    )
    envelope = json.loads(stdout)
    assert result == 1
    assert [request.function for request in requests] == [
        "qa.plan.list",
        "qa.plan.get",
    ]
    assert envelope["success"] is False
    assert envelope["error"]["code"] == code
    assert editor_path is not None
    assert editor_path.exists()
    assert str(editor_path) in envelope["error"]["message"]
    assert stderr == ""
    editor_path.unlink()


def test_conflict_preserves_the_valid_edited_document() -> None:
    requests: list[FunctionCallRequest] = []
    editor_path: Path | None = None

    def editor(argv, *, check):
        nonlocal editor_path
        editor_path = Path(argv[-1])
        return subprocess.CompletedProcess(argv, 0)

    result, _stdout, stderr = run_cli(
        requests,
        editor,
        *EDIT_ARGS,
        edit_error=FunctionError(
            code="conflict",
            message="plan changed",
            jsonpath="$.payload.base_updated_at",
        ),
    )

    assert result == 1
    assert requests[-1].function == "qa.plan.edit"
    assert editor_path is not None
    assert editor_path.exists()
    assert "preserved" in stderr
    editor_path.unlink()


def test_slug_change_is_refused_without_a_write() -> None:
    requests: list[FunctionCallRequest] = []
    editor_path: Path | None = None

    def editor(argv, *, check):
        nonlocal editor_path
        editor_path = Path(argv[-1])
        document = json.loads(editor_path.read_text(encoding="utf-8"))
        document["slug"] = "renamed-plan"
        editor_path.write_text(json.dumps(document), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)

    result, _stdout, stderr = run_cli(
        requests,
        editor,
        *EDIT_ARGS,
    )

    assert result == 1
    assert [request.function for request in requests] == [
        "qa.plan.list",
        "qa.plan.get",
    ]
    assert "slug is immutable" in stderr
    assert editor_path is not None
    editor_path.unlink()


def test_help_teaches_worked_example_cas_recovery_and_exit_codes() -> None:
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        result = cli_main(["qa", "plan", "edit", "--help"])
    help_text = stdout.getvalue()

    assert result == 0
    assert "yoke qa plan edit release-readiness" in help_text
    assert "updated_at token" in help_text
    assert "Reopen the command on the latest plan" in help_text
    assert "--json        emit a typed response envelope" in help_text
    assert "Exit codes: 0 saved or unchanged" in help_text
