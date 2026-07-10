"""Shared request, runner, and authority fixtures for runner status tests."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import github_actions_runners
from yoke_core.domain import github_actions_runner_status_readiness
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)


_RESOLVED = ProjectGithubAuth(
    project="yoke",
    repo="upyoke/yoke",
    token="ghs_test_token",
    permissions={"administration": "read", "actions_variables": "read"},
)

_APP_SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:yoke-github-app-AbCdEf"
)


def _renderer_settings(
    *,
    runner_settings: dict[str, Any] | None = None,
    github_permissions: dict[str, str] | None = None,
    environment_settings: dict[str, Any] | None = None,
) -> ProjectRendererSettings:
    selected_environment_settings = (
        {
            "github_app": {
                "issuer": "Iv1.runner-fleet",
                "api_url": "https://api.github.com",
                "private_key_secret_arn": _APP_SECRET_ARN,
            },
        }
        if environment_settings is None
        else environment_settings
    )
    environment = RendererEnvironmentSettings(
        id="yoke-api-stage",
        name="stage",
        settings=selected_environment_settings,
    )
    return ProjectRendererSettings(
        project="yoke",
        deploy_namespace="yoke",
        display_name="Yoke",
        site_id="yoke-api",
        site_settings={},
        primary_environment=environment,
        environments=(environment,),
        capabilities={
            "aws-admin": {"region": "us-east-1"},
            "github": {
                "repo_owner": "upyoke",
                "repo_name": "yoke",
                "installation_id": "123456",
                "repository_id": "789012",
                "api_url": "https://api.github.com",
                "permissions": (
                    {
                        "administration": "write",
                        "actions_variables": "write",
                        "repository_hooks": "write",
                    }
                    if github_permissions is None
                    else github_permissions
                ),
            },
            "github-actions-runner-fleet": (
                {
                    "repo": "upyoke/yoke",
                    "github_capability": "github",
                    "github_app_environment": "yoke-api-stage",
                    "routing_enabled": True,
                }
                if runner_settings is None
                else runner_settings
            ),
        },
    )


def _make_request(
    payload: Optional[Dict[str, Any]] = None,
    *,
    target_kind: str = "global",
    include_project: bool = True,
) -> FunctionCallRequest:
    if payload is None:
        payload = {"repo": "upyoke/yoke"}
    payload = dict(payload)
    if include_project:
        payload.setdefault("project", "yoke")
    return FunctionCallRequest(
        function="github_actions.runners.status",
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind=target_kind),
        payload=payload,
    )


@pytest.fixture(autouse=True)
def _auth_resolved(monkeypatch):
    calls = []

    def _resolve(project, **kwargs):
        calls.append((project, kwargs))
        return _RESOLVED

    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        _resolve,
    )
    return calls


@pytest.fixture(autouse=True)
def _runner_capability_absent(monkeypatch):
    monkeypatch.setattr(
        github_actions_runners,
        "cmd_capability_get_settings",
        lambda project, cap_type: None,
    )
    monkeypatch.setattr(
        github_actions_runner_status_readiness,
        "load_project_renderer_settings",
        lambda project: _renderer_settings(),
    )


def _runner(
    *,
    labels=("self-hosted", "Linux", "ARM64", "yoke-github-actions"),
    status="online",
    busy=False,
) -> Dict[str, Any]:
    return {
        "id": 7,
        "name": "yoke-github-actions-1",
        "status": status,
        "busy": busy,
        "labels": [{"name": label} for label in labels],
    }


def _configure_runner_capability(
    monkeypatch,
    *,
    routing_enabled: bool = True,
) -> None:
    settings = {
        "repo": "upyoke/yoke",
        "github_capability": "github",
        "github_app_environment": "yoke-api-stage",
        "routing_enabled": routing_enabled,
    }
    monkeypatch.setattr(
        github_actions_runners,
        "cmd_capability_get_settings",
        lambda project, cap_type: json.dumps(settings),
    )
