"""CI gate reports a missing workflow without guessing authorization."""

from __future__ import annotations

import json
import subprocess
from unittest import mock

from yoke_core.domain import deploy_pipeline_gates


def _adapter(response: dict, returncode: int = 1) -> mock.MagicMock:
    return mock.patch.object(
        deploy_pipeline_gates,
        "_github_actions",
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=returncode,
            stdout=json.dumps(response),
            stderr="",
        ),
    )


def test_missing_workflow_names_file_and_repo_not_authorization():
    response = {
        "success": False,
        "error": {
            "code": "workflow_not_found",
            "message": (
                "declared workflow platform-quick-verification.yml "
                "does not exist in upyoke/platform"
            ),
        },
        "result": {},
    }
    with (
        mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="platform-quick-verification.yml",
        ),
        _adapter(response),
    ):
        passed, message = deploy_pipeline_gates._check_ci_gate(
            "upyoke/platform",
            "platform",
            30,
            branch="main",
        )

    assert passed is False
    assert "platform-quick-verification.yml" in message
    assert "upyoke/platform" in message
    assert "ci_workflow_file" in message
    assert "authorization" not in message.lower()
    assert "transport" not in message.lower()


def test_rest_auth_error_still_reports_as_authorization():
    response = {
        "success": False,
        "error": {
            "code": "rest_auth_error",
            "message": "HTTP 401: bad credentials",
        },
        "result": {},
    }
    with (
        mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ),
        _adapter(response),
    ):
        passed, message = deploy_pipeline_gates._check_ci_gate(
            "owner/repo",
            "yoke",
            30,
            branch="main",
        )

    assert passed is False
    assert "rest_auth_error" in message
    assert "authorization failure" in message


def test_auth_error_still_reports_as_authorization():
    response = {
        "success": False,
        "error": {
            "code": "project_auth_error",
            "message": "user authorization unavailable",
        },
        "result": {},
    }
    with (
        mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ),
        _adapter(response),
    ):
        passed, message = deploy_pipeline_gates._check_ci_gate(
            "owner/repo",
            "yoke",
            30,
            branch="main",
        )

    assert passed is False
    assert "project_auth_error" in message
    assert "authorization failure" in message
    assert "not a failing test conclusion" in message


def test_unknown_adapter_error_does_not_guess_authorization():
    response = {
        "success": False,
        "error": {"code": "weird_code", "message": "something else"},
        "result": {},
    }
    with (
        mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ),
        _adapter(response),
    ):
        passed, message = deploy_pipeline_gates._check_ci_gate(
            "owner/repo",
            "yoke",
            30,
            branch="main",
        )

    assert passed is False
    assert "weird_code" in message
    assert "failure class is unknown" in message
    assert "authorization or transport" not in message
