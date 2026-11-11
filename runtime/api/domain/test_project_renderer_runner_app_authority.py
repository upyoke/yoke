"""Capability-owned GitHub App authority for runner-fleet values."""

from __future__ import annotations

from dataclasses import replace

import pytest

from yoke_core.domain.project_renderer_pulumi_runner_fleet import (
    runner_fleet_values,
)
from yoke_core.domain.project_renderer_settings import ProjectRendererSettings
from runtime.api.domain.project_settings_test_support import (
    _settings_from_context,
)


def _values(settings: ProjectRendererSettings) -> dict[str, str]:
    return runner_fleet_values(
        settings, fallback_repo="acme-org/externalwebapp", enabled=True
    )


_APP_SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:yoke-github-app-AbCdEf"
)


def _app(issuer: str = "Iv1.runner-fleet") -> dict[str, str]:
    return {
        "issuer": issuer,
        "api_url": "https://api.github.com",
        "private_key_secret_arn": _APP_SECRET_ARN,
    }


def _github(permissions: dict[str, str] | None = None) -> dict[str, object]:
    return {
        "repo_owner": "acme-org",
        "repo_name": "externalwebapp",
        "installation_id": "123456",
        "repository_id": "789012",
        "api_url": "https://api.github.com",
        "permissions": permissions or {
            "administration": "write",
            "actions_variables": "write",
            "repository_hooks": "write",
        },
    }


def _settings(
    *, github_app: dict[str, str] | None,
) -> ProjectRendererSettings:
    base = _settings_from_context(
        "externalwebapp",
    )
    capabilities = dict(base.capabilities)
    capabilities["github"] = _github()
    runner: dict[str, object] = {
        "github_capability": "github",
        "routing_enabled": True,
    }
    if github_app is not None:
        runner["github_app"] = github_app
    capabilities["github-actions-runner-fleet"] = runner
    return replace(base, capabilities=capabilities)


def test_enabled_runner_fleet_requires_explicit_app_authority(tmp_path):
    settings = _settings(github_app=None)

    with pytest.raises(ValueError, match="requires github_app"):
        _values(settings)


def test_runner_fleet_uses_capability_owned_app_authority(tmp_path):
    settings = _settings(github_app=_app("Iv1.runner-fleet-app"))

    values = _values(settings)

    assert values["runner_fleet_github_app_issuer"] == "Iv1.runner-fleet-app"
    assert values["runner_fleet_github_private_key_secret_arn"] == _APP_SECRET_ARN


def test_enabled_runner_fleet_requires_repository_hooks_write(tmp_path):
    settings = _settings(github_app=_app())
    capabilities = dict(settings.capabilities)
    capabilities["github"] = _github({
        "administration": "write",
        "actions_variables": "write",
    })
    settings = replace(settings, capabilities=capabilities)

    with pytest.raises(ValueError, match=r"Webhooks: write \(repository_hooks\)"):
        _values(settings)


def test_enabled_runner_fleet_requires_actions_variables_write(tmp_path):
    settings = _settings(github_app=_app())
    capabilities = dict(settings.capabilities)
    capabilities["github"] = _github({
        "administration": "write",
        "repository_hooks": "write",
    })
    settings = replace(settings, capabilities=capabilities)

    with pytest.raises(
        ValueError, match=r"Variables: write \(actions_variables\)",
    ):
        _values(settings)


def test_runner_fleet_uses_explicit_privileged_github_capability(tmp_path):
    settings = _settings(github_app=_app())
    capabilities = dict(settings.capabilities)
    custom_github = _github()
    capabilities["github-automation"] = custom_github
    runner = dict(capabilities["github-actions-runner-fleet"])
    runner["github_capability"] = "github-automation"
    capabilities["github-actions-runner-fleet"] = runner
    settings = replace(settings, capabilities=capabilities)

    values = _values(settings)

    assert values["runner_fleet_github_capability"] == "github-automation"
    assert values["runner_fleet_github_installation_id"] == "123456"


def test_disabled_routing_still_requires_permission_to_delete_variable(
    tmp_path,
):
    settings = _settings(github_app=_app())
    capabilities = dict(settings.capabilities)
    capabilities["github"] = _github({
        "administration": "write",
        "repository_hooks": "write",
    })
    runner = dict(capabilities["github-actions-runner-fleet"])
    runner["routing_enabled"] = False
    capabilities["github-actions-runner-fleet"] = runner
    settings = replace(settings, capabilities=capabilities)

    with pytest.raises(
        ValueError, match=r"Variables: write \(actions_variables\)",
    ):
        _values(settings)
