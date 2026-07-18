"""Pulumi renderer values sourced from project capabilities."""

from __future__ import annotations

import json
from pathlib import Path
import runpy

import pytest

from yoke_core.domain import (
    project_renderer_pulumi,
    project_renderer_pulumi_runner_fleet,
)
from yoke_core.domain.project_renderer_pulumi import render_pulumi_stack_yaml
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


def _runner_app(
    *,
    api_url: str = "https://api.github.com",
    private_key_secret_arn: str = (
        "arn:aws:secretsmanager:us-east-1:123456789012:"
        "secret:yoke-github-app-AbCdEf"
    ),
) -> dict[str, str]:
    return {
        "issuer": "Iv1.runner-fleet",
        "api_url": api_url,
        "private_key_secret_arn": private_key_secret_arn,
    }


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
    assert result["github_api_url"] == "https://api.github.com"
    assert result["manage_github_oidc_provider"] == "false"


def test_delivery_ci_resources_come_from_environment_authority(tmp_path):
    base = _settings_from_context("buzz", {"projectName": "buzz"})
    assert base.primary_environment is not None
    base.primary_environment.settings["distribution"] = {
        "bucket_name": "acme-distribution-prod"
    }
    base.primary_environment.settings["github_app"] = {
        "private_key_secret_arn": (
            "arn:aws:secretsmanager:us-east-1:123456789012:"
            "secret:acme/prod/github-app-private-key-AbCdEf"
        )
    }

    result = project_renderer_pulumi.gather_pulumi_values(
        "buzz", _make_project_root(tmp_path, "buzz"), base,
    )

    assert result["delivery_distribution_bucket_names_json"] == (
        '["acme-distribution-prod"]'
    )
    assert "github-app-private-key-AbCdEf" in (
        result["github_app_private_key_secret_arns_json"]
    )


def test_delivery_ci_cloudfront_id_does_not_require_distribution_bucket(tmp_path):
    base = _settings_from_context(
        "external-webapp",
        {"projectName": "external-webapp"},
        {"cloudfront_id": "EEXTERNAL"},
    )

    result = project_renderer_pulumi.gather_pulumi_values(
        "external-webapp",
        _make_project_root(tmp_path, "external-webapp"),
        base,
    )

    assert result["delivery_cloudfront_distribution_ids_json"] == '["EEXTERNAL"]'
    assert result["delivery_distribution_bucket_names_json"] == "[]"


def test_list_cdn_distribution_flows_to_exact_delivery_policy(tmp_path):
    base = _settings_from_context("buzz", {"projectName": "buzz"})
    base.site_settings["cdn"] = [{"distribution_id": "ELISTSHAPED"}]
    root = _make_project_root(tmp_path, "buzz")

    values = project_renderer_pulumi.gather_pulumi_values("buzz", root, base)
    template = (
        Path(__file__).resolve().parents[3]
        / "templates"
        / "webapp"
        / "infra"
        / "Pulumi.registry-stack.yaml.tmpl"
    )
    rendered = render_pulumi_stack_yaml(template, values)
    distribution_ids = json.loads(
        values["delivery_cloudfront_distribution_ids_json"]
    )
    policy_path = template.parent / "webapp_registry_ci_policy.py"
    policy = json.loads(
        runpy.run_path(policy_path)["delivery_policy_json"](
            region="us-east-1",
            account_id="123456789012",
            deploy_namespace="buzz",
            state_bucket="buzz-pulumi-state",
            kms_key_arn="arn:aws:kms:us-east-1:123456789012:key/state-key",
            distribution_bucket_names=[],
            cloudfront_distribution_ids=distribution_ids,
            github_app_private_key_secret_arns=[],
        )
    )

    assert values["cloudfront_id"] == "ELISTSHAPED"
    assert distribution_ids == ["ELISTSHAPED"]
    assert "webapp-infra:cloudfront_distribution_ids: [\"ELISTSHAPED\"]" in rendered
    by_sid = {statement["Sid"]: statement for statement in policy["Statement"]}
    assert by_sid["InvalidateProjectDistributions"]["Resource"] == [
        "arn:aws:cloudfront::123456789012:distribution/ELISTSHAPED"
    ]


def test_runner_fleet_keys_from_capability(tmp_path):
    base = _settings_from_context(
        "buzz", {"projectName": "buzz", "stacks": ["runner-fleet"]},
    )
    assert base.primary_environment is not None
    base.primary_environment.settings["capabilities"] = ["vps"]
    base.primary_environment.settings["pulumi"] = {
        "activation_state": "active",
        "stack_name": "buzz-prod",
    }
    capabilities = dict(base.capabilities)
    capabilities["github"] = {
        "repo_owner": "acme-org",
        "repo_name": "buzz",
        "installation_id": "123456",
        "repository_id": "789012",
        "api_url": "https://api.github.com",
        "permissions": {
            "administration": "write",
            "actions_variables": "write",
            "repository_hooks": "write",
        },
    }
    capabilities["github-actions-runner-fleet"] = {
        "repo": "acme-org/buzz",
        "github_capability": "github",
        "github_app": _runner_app(),
        "runner_labels": [
            "self-hosted", "Linux", "ARM64", "yoke-github-actions",
        ],
        "routing_enabled": True,
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
        "network": {
            "deployment_ssh_environments": [base.primary_environment.id],
        },
    }
    root = _make_project_root(tmp_path, "buzz")

    result = project_renderer_pulumi.gather_pulumi_values(
        "buzz", root, _with_capabilities(base, capabilities),
    )

    assert result["runner_fleet_repo"] == "acme-org/buzz"
    assert result["runner_fleet_aws_capability"] == "aws-admin"
    assert result["runner_fleet_aws_region"] == "us-east-1"
    assert result["runner_fleet_github_installation_id"] == "123456"
    assert result["runner_fleet_github_repository_id"] == "789012"
    assert result["runner_fleet_github_api_url"] == "https://api.github.com"
    assert result["runner_fleet_github_web_url"] == "https://github.com"
    assert result["runner_fleet_labels_json"] == (
        '["self-hosted","Linux","ARM64","yoke-github-actions"]'
    )
    assert result["runner_fleet_variable_name"] == "YOKE_LINUX_RUNS_ON"
    assert result["runner_fleet_routing_enabled"] == "true"
    assert result["runner_fleet_instance_type"] == "m7g.2xlarge"
    assert result["runner_fleet_root_volume_gb"] == "100"
    assert result["runner_fleet_idle_shutdown_minutes"] == "15"
    assert result["runner_fleet_shutdown_mode"] == "terminate"
    assert result["runner_fleet_deployment_ssh_stack_outputs_json"] == (
        '{"buzz-prod":"originElasticIpAddress"}'
    )


def test_enabled_runner_fleet_requires_explicit_github_capability(tmp_path):
    base = _settings_from_context(
        "buzz", {"projectName": "buzz", "stacks": ["runner-fleet"]},
    )
    root = _make_project_root(tmp_path, "buzz")

    with pytest.raises(ValueError, match="requires explicit github_capability"):
        project_renderer_pulumi.gather_pulumi_values("buzz", root, base)


def test_enabled_runner_fleet_requires_capability_app_config(tmp_path):
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
        "permissions": {
            "administration": "write",
            "actions_variables": "write",
            "repository_hooks": "write",
        },
    }
    capabilities["github-actions-runner-fleet"] = {
        "github_capability": "github",
    }
    root = _make_project_root(tmp_path, "buzz")

    with pytest.raises(ValueError, match="requires github_app"):
        project_renderer_pulumi.gather_pulumi_values(
            "buzz", root, _with_capabilities(base, capabilities),
        )


def test_enabled_runner_fleet_rejects_unsafe_secret_arn(tmp_path):
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
        "permissions": {
            "administration": "write",
            "actions_variables": "write",
            "repository_hooks": "write",
        },
    }
    capabilities["github-actions-runner-fleet"] = {
        "github_capability": "github",
        "github_app": _runner_app(
            private_key_secret_arn=(
                "arn:aws:secretsmanager:unsafe\nconfig: value"
            ),
        ),
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
    capabilities = dict(base.capabilities)
    capabilities["github"] = {
        "repo_owner": "acme-org", "repo_name": "buzz",
        "installation_id": "123456", "repository_id": "789012",
        "api_url": "https://api.github.com",
        "permissions": {
            "administration": "write",
            "actions_variables": "write",
            "repository_hooks": "write",
        },
    }
    capabilities["github-actions-runner-fleet"] = {
        "repo": "other/repo",
        "github_capability": "github",
        "github_app": _runner_app(),
    }
    root = _make_project_root(tmp_path, "buzz")

    with pytest.raises(ValueError, match="must match the verified GitHub App"):
        project_renderer_pulumi.gather_pulumi_values(
            "buzz", root, _with_capabilities(base, capabilities),
        )


def test_enabled_runner_fleet_rejects_app_origin_mismatch(tmp_path):
    base = _settings_from_context(
        "buzz", {"projectName": "buzz", "stacks": ["runner-fleet"]},
    )
    capabilities = dict(base.capabilities)
    capabilities["github"] = {
        "repo_owner": "acme-org", "repo_name": "buzz",
        "installation_id": "123456", "repository_id": "789012",
        "api_url": "https://api.github.com",
        "permissions": {
            "administration": "write",
            "actions_variables": "write",
            "repository_hooks": "write",
        },
    }
    capabilities["github-actions-runner-fleet"] = {
        "github_capability": "github",
        "github_app": _runner_app(
            api_url="https://github.example/api/v3",
        ),
    }

    with pytest.raises(ValueError, match="must match the verified"):
        project_renderer_pulumi.gather_pulumi_values(
            "buzz", tmp_path, _with_capabilities(base, capabilities),
        )


def test_enabled_runner_fleet_requires_administration_write(tmp_path):
    base = _settings_from_context(
        "buzz", {"projectName": "buzz", "stacks": ["runner-fleet"]},
    )
    capabilities = dict(base.capabilities)
    capabilities["github"] = {
        "repo_owner": "acme-org", "repo_name": "buzz",
        "installation_id": "123456", "repository_id": "789012",
        "api_url": "https://api.github.com",
        "permissions": {
            "administration": "read",
            "actions_variables": "write",
            "repository_hooks": "write",
        },
    }
    capabilities["github-actions-runner-fleet"] = {
        "github_capability": "github",
        "github_app": _runner_app(),
    }

    with pytest.raises(ValueError, match="Administration: write"):
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
