"""A GitHub outage during a token mint is not a credentials failure.

GitHub failing (5xx, rate limit, network, timeout) is ``github_unavailable``
with a retry recovery; GitHub refusing the App or its installation
(401/403/404/422) is ``token_mint_failed`` with the repair that status names.
Every token-mint caller sees one classification.
"""

# Imported pytest fixtures intentionally share names with test parameters.
# ruff: noqa: F811

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from runtime.api.domain.project_github_auth_test_support import (
    app_bound_db as app_bound_db,
    control_plane_config as control_plane_config,
    db_path as db_path,
)
from yoke_core.domain import github_actions_commit_runs_read as commit_runs_read
from yoke_core.domain import project_github_auth as pga
from yoke_core.domain.deploy_pipeline_ci_recovery import ci_adapter_failure_message
from yoke_core.domain.deploy_pipeline_github_workflow_dispatch import (
    trigger_with_recovery_retries,
)
from yoke_core.domain.github_app_token_models import (
    GitHubAppTokenError,
    GitHubAppTokenResponseError,
    GitHubAppTokenUnavailableError,
)
from yoke_core.domain.handlers.github_actions_set import _auth_failed
from yoke_core.domain.project_github_token_mint_failure import token_mint_failure


def _http(status: int, body: str = "") -> GitHubAppTokenResponseError:
    return GitHubAppTokenResponseError(
        "GitHub installation token request failed", status=status, body=body
    )


@pytest.mark.parametrize("status", [500, 502, 503, 504, 429])
def test_github_server_failures_are_github_unavailable(status: int):
    error = token_mint_failure("yoke", _http(status, '{"message":"Server Error"}'))

    assert isinstance(error, pga.GitHubUnavailable)
    assert error.code == "github_unavailable"
    assert error.http_status == status
    assert f"HTTP {status}: Server Error" in str(error)
    hint = pga.repair_command_hint(error, "yoke")
    assert "GitHub is failing" in hint
    assert "credentials" in hint and "repair App" not in hint


def test_secondary_rate_limit_403_is_github_unavailable():
    body = json.dumps({"message": "You have exceeded a secondary rate limit."})

    error = token_mint_failure("yoke", _http(403, body))

    assert isinstance(error, pga.GitHubUnavailable)
    assert error.http_status == 403


def test_network_and_timeout_failures_are_github_unavailable():
    error = token_mint_failure(
        "yoke",
        GitHubAppTokenUnavailableError(
            "GitHub installation token request was unavailable"
        ),
    )

    assert isinstance(error, pga.GitHubUnavailable)
    assert error.http_status is None
    assert "request was unavailable" in str(error)


@pytest.mark.parametrize(
    ("status", "names"),
    [
        (401, "rejected the App JWT"),
        (403, "refused the App installation"),
        (404, "no such App installation"),
        (422, "refused the requested repository or permissions"),
    ],
)
def test_github_refusals_name_their_repair(status: int, names: str):
    error = token_mint_failure("yoke", _http(status, '{"message":"Bad credentials"}'))

    assert isinstance(error, pga.TokenMintFailed)
    assert error.code == "token_mint_failed"
    assert error.http_status == status
    assert f"HTTP {status}: Bad credentials" in str(error)
    hint = pga.repair_command_hint(error, "yoke")
    assert names in hint
    assert hint.endswith("project yoke")


def test_local_mint_failure_keeps_the_credentials_repair():
    error = token_mint_failure(
        "yoke", GitHubAppTokenError("GitHub App JWT signing failed")
    )

    assert isinstance(error, pga.TokenMintFailed)
    assert error.http_status is None
    assert pga.repair_command_hint(error, "yoke") == (
        "repair App credentials or installation access for project yoke"
    )


def test_long_non_json_body_is_one_bounded_line():
    error = token_mint_failure("yoke", _http(502, "<html>\n" + "x" * 500 + "\n</html>"))

    message = str(error)
    assert "\n" not in message
    assert message.endswith("...)")
    assert len(message) < 300


def test_resolve_raises_github_unavailable_through_the_mint(app_bound_db: str):
    def fail_mint(**_kwargs):
        raise _http(502, '{"message":"Bad Gateway"}')

    with pytest.raises(pga.GitHubUnavailable) as info:
        pga.resolve_project_github_auth(
            "yoke", db_path=app_bound_db, token_minter=fail_mint
        )

    assert info.value.http_status == 502
    assert "HTTP 502: Bad Gateway" in str(info.value)


def test_handlers_report_github_unavailable_as_its_own_code():
    unavailable = pga.GitHubUnavailable("yoke", "GitHub is unavailable (HTTP 502)")
    refused = pga.TokenMintFailed("yoke", "GitHub refused the request (HTTP 401)")

    unavailable_error = _auth_failed(unavailable, "yoke").error
    refused_error = _auth_failed(refused, "yoke").error

    assert unavailable_error.code == "github_unavailable"
    assert "Repair: GitHub is failing" in unavailable_error.message
    assert refused_error.code == "project_auth_error"


def test_workflow_dispatch_retries_github_unavailable(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_github_workflow_dispatch.time.sleep",
        lambda _seconds: None,
    )
    results = [
        SimpleNamespace(
            returncode=4, stdout='{"error":{"code":"github_unavailable"}}', stderr=""
        ),
        SimpleNamespace(returncode=0, stdout="{}", stderr=""),
    ]

    result = trigger_with_recovery_retries(
        ["trigger"],
        github_actions=lambda *_args, **_kwargs: results.pop(0),
        project="yoke",
        sd=None,
        timeout_sec=60,
    )

    assert result.returncode == 0
    assert results == []


def test_ci_gate_names_github_unavailable_as_transient():
    message = ci_adapter_failure_message(
        "github_unavailable",
        "github_unavailable: GitHub is unavailable (HTTP 502)",
        workflow="ci.yml",
        repo="upyoke/yoke",
    )

    assert "GitHub itself is failing" in message
    assert "re-drive the deployment once GitHub recovers" in message
    assert "authorization failure" not in message


def test_commit_run_read_separates_github_unavailable(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._github_actions",
        lambda *args, project, **kwargs: subprocess.CompletedProcess(
            args=list(args),
            returncode=4,
            stdout=json.dumps(
                {"error": {"code": "github_unavailable", "message": "x"}}
            ),
            stderr="",
        ),
    )

    with pytest.raises(commit_runs_read.CommitRunUnavailableError):
        commit_runs_read.matching_runs("yoke", "a" * 40, "")
