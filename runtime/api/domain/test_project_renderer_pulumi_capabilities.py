"""Pulumi renderer values sourced from project capabilities."""

from __future__ import annotations

import pytest

from yoke_core.domain import (
    project_renderer_pulumi,
    project_renderer_pulumi_runner_fleet,
)
from yoke_core.domain.project_renderer_settings import ProjectRendererSettings
from runtime.api.domain.test_project_renderer_pulumi import (
    _make_project_root,
    _settings_from_context,
)


def _with_capabilities(base: ProjectRendererSettings, capabilities: dict):
    return ProjectRendererSettings(
        project=base.project,
        deploy_namespace=base.deploy_namespace,
        display_name=base.display_name,
        site_id=base.site_id,
        site_settings=base.site_settings,
        primary_environment=base.primary_environment,
        environments=base.environments,
        capabilities=capabilities,
    )


def test_github_ci_keys_from_capability(tmp_path):
    base = _settings_from_context("buzz", {"projectName": "buzz"})
    capabilities = dict(base.capabilities)
    capabilities["github"] = {
        "repo_owner": "acme-org",
        "repo_name": "buzz",
        "ci_oidc_manage_provider": False,
    }
    root = _make_project_root(tmp_path, "buzz")

    result = project_renderer_pulumi.gather_pulumi_values(
        "buzz", root, _with_capabilities(base, capabilities),
    )

    assert result["github_repo_slug"] == "acme-org/buzz"
    assert result["manage_github_oidc_provider"] == "false"


def test_runner_fleet_keys_from_capability(tmp_path):
    base = _settings_from_context(
        "buzz", {"projectName": "buzz", "stacks": ["runner-fleet"]},
    )
    assert base.primary_environment is not None
    base.primary_environment.settings["github_app"] = {
        "issuer": "Iv1.runner-fleet",
        "api_url": "https://api.github.com",
        "private_key_secret_arn": (
            "arn:aws:secretsmanager:us-east-1:123456789012:"
            "secret:yoke-github-app-AbCdEf"
        ),
    }
    capabilities = dict(base.capabilities)
    capabilities["github"] = {
        "repo_owner": "acme-org",
        "repo_name": "buzz",
        "installation_id": "123456",
        "repository_id": "789012",
        "api_url": "https://api.github.com",
        "permissions": {"administration": "write"},
    }
    capabilities["github-actions-runner-fleet"] = {
        "repo": "acme-org/buzz",
        "runner_labels": [
            "self-hosted", "Linux", "ARM64", "yoke-github-actions",
        ],
        "desired_runner_count": 1,
        "max_runner_count": 1,
        "instance": {
            "instance_type": "m7g.2xlarge",
            "architecture": "arm64",
            "root_volume_gb": 100,
        },
        "lifecycle": {
            "start_mode": "autoscaled",
            "idle_shutdown_minutes": 15,
            "ephemeral_runners": True,
            "shutdown_mode": "terminate",
        },
    }
    root = _make_project_root(tmp_path, "buzz")

    result = project_renderer_pulumi.gather_pulumi_values(
        "buzz", root, _with_capabilities(base, capabilities),
    )

    assert result["runner_fleet_repo"] == "acme-org/buzz"
    assert result["runner_fleet_github_installation_id"] == "123456"
    assert result["runner_fleet_github_repository_id"] == "789012"
    assert result["runner_fleet_github_api_url"] == "https://api.github.com"
    assert result["runner_fleet_github_web_url"] == "https://github.com"
    assert result["runner_fleet_labels_json"] == (
        '["self-hosted","Linux","ARM64","yoke-github-actions"]'
    )
    assert result["runner_fleet_instance_type"] == "m7g.2xlarge"
    assert result["runner_fleet_root_volume_gb"] == "100"
    assert result["runner_fleet_idle_shutdown_minutes"] == "15"
    assert result["runner_fleet_shutdown_mode"] == "terminate"


def test_enabled_runner_fleet_requires_verified_binding(tmp_path):
    base = _settings_from_context(
        "buzz", {"projectName": "buzz", "stacks": ["runner-fleet"]},
    )
    root = _make_project_root(tmp_path, "buzz")

    with pytest.raises(ValueError, match="verified GitHub App repository binding"):
        project_renderer_pulumi.gather_pulumi_values("buzz", root, base)


def test_enabled_runner_fleet_requires_environment_app_config(tmp_path):
    base = _settings_from_context(
        "buzz", {"projectName": "buzz", "stacks": ["runner-fleet"]},
    )
    capabilities = dict(base.capabilities)
    capabilities["github"] = {
        "repo_owner": "acme-org",
        "repo_name": "buzz",
        "installation_id": "123456",
        "repository_id": "789012",
        "api_url": "https://api.github.com",
        "permissions": {"administration": "write"},
    }
    root = _make_project_root(tmp_path, "buzz")

    with pytest.raises(ValueError, match="settings.github_app"):
        project_renderer_pulumi.gather_pulumi_values(
            "buzz", root, _with_capabilities(base, capabilities),
        )


def test_enabled_runner_fleet_rejects_unsafe_secret_arn(tmp_path):
    base = _settings_from_context(
        "buzz", {"projectName": "buzz", "stacks": ["runner-fleet"]},
    )
    assert base.primary_environment is not None
    base.primary_environment.settings["github_app"] = {
        "issuer": "Iv1.runner-fleet",
        "api_url": "https://api.github.com",
        "private_key_secret_arn": "arn:aws:secretsmanager:unsafe\nconfig: value",
    }
    capabilities = dict(base.capabilities)
    capabilities["github"] = {
        "repo_owner": "acme-org",
        "repo_name": "buzz",
        "installation_id": "123456",
        "repository_id": "789012",
        "api_url": "https://api.github.com",
        "permissions": {"administration": "write"},
    }
    root = _make_project_root(tmp_path, "buzz")

    with pytest.raises(ValueError, match="complete AWS Secrets Manager ARN"):
        project_renderer_pulumi.gather_pulumi_values(
            "buzz", root, _with_capabilities(base, capabilities),
        )


def test_enabled_runner_fleet_rejects_repo_override(tmp_path):
    base = _settings_from_context(
        "buzz", {"projectName": "buzz", "stacks": ["runner-fleet"]},
    )
    assert base.primary_environment is not None
    base.primary_environment.settings["github_app"] = {
        "issuer": "Iv1.runner-fleet",
        "api_url": "https://api.github.com",
        "private_key_secret_arn": (
            "arn:aws:secretsmanager:us-east-1:123456789012:"
            "secret:yoke-github-app-AbCdEf"
        ),
    }
    capabilities = dict(base.capabilities)
    capabilities["github"] = {
        "repo_owner": "acme-org", "repo_name": "buzz",
        "installation_id": "123456", "repository_id": "789012",
        "api_url": "https://api.github.com",
        "permissions": {"administration": "write"},
    }
    capabilities["github-actions-runner-fleet"] = {"repo": "other/repo"}
    root = _make_project_root(tmp_path, "buzz")

    with pytest.raises(ValueError, match="must match the verified GitHub App"):
        project_renderer_pulumi.gather_pulumi_values(
            "buzz", root, _with_capabilities(base, capabilities),
        )


def test_enabled_runner_fleet_rejects_environment_origin_mismatch(tmp_path):
    base = _settings_from_context(
        "buzz", {"projectName": "buzz", "stacks": ["runner-fleet"]},
    )
    assert base.primary_environment is not None
    base.primary_environment.settings["github_app"] = {
        "issuer": "Iv1.runner-fleet",
        "api_url": "https://github.example/api/v3",
        "private_key_secret_arn": (
            "arn:aws:secretsmanager:us-east-1:123456789012:"
            "secret:yoke-github-app-AbCdEf"
        ),
    }
    capabilities = dict(base.capabilities)
    capabilities["github"] = {
        "repo_owner": "acme-org", "repo_name": "buzz",
        "installation_id": "123456", "repository_id": "789012",
        "api_url": "https://api.github.com",
        "permissions": {"administration": "write"},
    }

    with pytest.raises(ValueError, match="must match the verified"):
        project_renderer_pulumi.gather_pulumi_values(
            "buzz", tmp_path, _with_capabilities(base, capabilities),
        )


def test_enabled_runner_fleet_requires_administration_write(tmp_path):
    base = _settings_from_context(
        "buzz", {"projectName": "buzz", "stacks": ["runner-fleet"]},
    )
    assert base.primary_environment is not None
    base.primary_environment.settings["github_app"] = {
        "issuer": "Iv1.runner-fleet",
        "api_url": "https://api.github.com",
        "private_key_secret_arn": (
            "arn:aws:secretsmanager:us-east-1:123456789012:"
            "secret:yoke-github-app-AbCdEf"
        ),
    }
    capabilities = dict(base.capabilities)
    capabilities["github"] = {
        "repo_owner": "acme-org", "repo_name": "buzz",
        "installation_id": "123456", "repository_id": "789012",
        "api_url": "https://api.github.com",
        "permissions": {"administration": "read"},
    }

    with pytest.raises(ValueError, match="administration: write"):
        project_renderer_pulumi.gather_pulumi_values(
            "buzz", tmp_path, _with_capabilities(base, capabilities),
        )


@pytest.mark.parametrize(
    ("api_url", "web_url"),
    [
        ("https://api.github.com", "https://github.com"),
        ("https://api.acme.ghe.com", "https://acme.ghe.com"),
        ("https://github.acme.test/api/v3", "https://github.acme.test"),
    ],
)
def test_runner_fleet_derives_canonical_web_url(api_url, web_url):
    assert project_renderer_pulumi_runner_fleet._web_url_from_api(api_url) == web_url
