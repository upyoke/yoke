"""Capability-owned GitHub App authority for runner-fleet rendering."""

from __future__ import annotations

from dataclasses import replace

import pytest

from yoke_core.domain import project_renderer_pulumi
from yoke_core.domain.project_renderer_settings import ProjectRendererSettings
from runtime.api.domain.test_project_renderer_pulumi import _settings_from_context


_APP_SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:123456789012:"
    "secret:yoke-github-app-AbCdEf"
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
        "repo_name": "buzz",
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
        "buzz", {"projectName": "buzz", "stacks": ["runner-fleet"]},
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
        project_renderer_pulumi.gather_pulumi_values(
            "buzz", tmp_path, settings,
        )


def test_runner_fleet_uses_capability_owned_app_authority(tmp_path):
    settings = _settings(github_app=_app("Iv1.runner-fleet-app"))

    values = project_renderer_pulumi.gather_pulumi_values(
        "buzz", tmp_path, settings,
    )

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
        project_renderer_pulumi.gather_pulumi_values(
            "buzz", tmp_path, settings,
        )


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
        project_renderer_pulumi.gather_pulumi_values(
            "buzz", tmp_path, settings,
        )


def test_runner_fleet_refuses_noncanonical_github_capability(tmp_path):
    settings = _settings(github_app=_app())
    capabilities = dict(settings.capabilities)
    custom_github = _github()
    custom_github.update({"repo_owner": "other-org", "repo_name": "runners"})
    capabilities["github-automation"] = custom_github
    runner = dict(capabilities["github-actions-runner-fleet"])
    runner["github_capability"] = "github-automation"
    capabilities["github-actions-runner-fleet"] = runner
    settings = replace(settings, capabilities=capabilities)

    with pytest.raises(
        ValueError,
        match="(?s)github_capability.*must be 'github'",
    ):
        project_renderer_pulumi.gather_pulumi_values(
            "buzz", tmp_path, settings,
        )


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
        project_renderer_pulumi.gather_pulumi_values(
            "buzz", tmp_path, settings,
        )
