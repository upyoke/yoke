"""Tests for project_renderer_pulumi.py — Pulumi-specific rendering.

Covers the key-set contract for ``gather_pulumi_values``,
the camelCase-to-snake_case mapping, the stack-template substitution
contract on the stack template, and the seven-file output of
``render_pulumi_artifacts``.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import project_renderer_pulumi
from yoke_core.domain import project_renderer_pulumi_context
from yoke_core.domain import project_renderer_pulumi_instances
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)

_GATHER_VALUES_KEYS = {
    "project_display_name", "PROJECT_NAME_UPPER", "project_description",
    "project_name", "deploy_namespace", "cloudfront_domain", "cloudfront_id",
    "certificate_arn",
    "hosted_zone_id", "aws_account_id", "vps_description", "domain_name",
    "origin_host", "origin_ip", "aws_region", "ssh_user", "web_port",
    "api_port", "ephemeral_ttl_hours", "web_health_path", "web_smoke_paths",
    "domain", "api_port_base", "port_base", "port_range", "dns_provider",
    "configure_aws_credentials_action",
}
_VPS_KEYS = {
    "vps_instance_type",
    "vps_root_volume_gb",
    "vps_ssh_key_name",
    "vps_iam_instance_profile_name",
}
_PULUMI_KEYS = {
    "origin_id", "distribution_bucket_name", "kms_key_alias", "state_bucket",
    "pulumi_infra_stack_name", "pulumi_vps_stack_name",
    "pulumi_runner_fleet_stack_name", "domain_txt_records_json",
    "domain_mx_records_json",
}
_CI_KEYS = {
    "delivery_cloudfront_distribution_ids_json",
    "delivery_distribution_bucket_names_json",
    "github_api_url", "github_app_private_key_secret_arns_json",
    "github_repo_slug", "manage_github_oidc_provider",
}
_RUNNER_FLEET_KEYS = {
    "runner_fleet_aws_capability", "runner_fleet_aws_region",
    "runner_fleet_github_capability",
    "runner_fleet_repo", "runner_fleet_labels_json",
    "runner_fleet_variable_name", "runner_fleet_routing_enabled",
    "runner_fleet_github_repo_owner", "runner_fleet_github_repo_name",
    "runner_fleet_github_installation_id", "runner_fleet_github_repository_id",
    "runner_fleet_github_app_issuer", "runner_fleet_github_api_url",
    "runner_fleet_github_web_url",
    "runner_fleet_github_private_key_secret_arn",
    "runner_fleet_token_broker_function",
    "runner_fleet_instance_type", "runner_fleet_architecture",
    "runner_fleet_root_volume_gb", "runner_fleet_runner_count",
    "runner_fleet_max_runner_count", "runner_fleet_idle_shutdown_minutes",
    "runner_fleet_shutdown_mode", "runner_fleet_deployment_ssh_stack_outputs_json",
}


def _make_project_root(tmp_path: Path, project: str) -> Path:
    """Build a minimal project tree."""
    root = tmp_path / "repo"
    proj = root / "projects" / project
    proj.mkdir(parents=True)
    (proj / "config").write_text("aws_region=us-east-1\n")
    return root


def _settings_from_context(
    project: str, context: dict | None = None, base: dict | None = None,
) -> ProjectRendererSettings:
    """Build a small DB-settings snapshot for Pulumi unit tests."""
    context = context or {}
    base = base or {}
    domain = {
        "domain_name": base.get("domain_name", context.get("domainName", "")),
        "hosted_zone_id": base.get("hosted_zone_id", context.get("hostedZoneId", "")),
        "certificate_arn": base.get(
            "certificate_arn", context.get("certificateArn", ""),
        ),
        "dns_provider": base.get("dns_provider", "route53"),
        "manage_registration": context.get("manageRegistration", False),
        "txt_records": context.get("txtRecords", []),
        "mx_records": context.get("mxRecords", []),
    }
    site_settings = {
        "domains": [domain],
        "cdn": {
            "origin_id": context.get("originId", ""),
            "distribution_bucket_name": context.get(
                "distributionBucketName", ""
            ),
            "distribution_id": base.get("cloudfront_id", ""),
            "distribution_domain": base.get("cloudfront_domain", ""),
        },
    }
    env_settings = {
        "hosts": {"origin": base.get("origin_host", context.get("originHost", ""))},
        "servers": [{
            "host": base.get("origin_ip", ""),
            "instance_type": context.get("vpsInstanceType", ""),
            "root_volume_gb": context.get("vpsRootVolumeGb", ""),
            "aws_key_pair_name": context.get("vpsSshKeyName", ""),
            "iam_instance_profile_name": context.get(
                "vpsIamInstanceProfileName", ""
            ),
        }],
    }
    capabilities = {
        "aws-admin": {
            "region": base.get(
                "aws_region", context.get("awsRegion", "us-east-1")
            ),
            "account_id": base.get(
                "aws_account_id", context.get("awsAccountId", ""),
            ),
        },
        "pulumi-state": {
            "kms_key_alias": context.get("kmsKeyAlias", ""),
            "state_bucket": context.get("stateBucket", ""),
            "stacks": context.get("stacks", []),
            "infra_stack_name": context.get("pulumiInfraStackName", ""),
            "vps_stack_name": context.get("pulumiVpsStackName", ""),
        },
        "container-registry": {
            "repository": context.get("containerRepositoryName", ""),
        },
        "ssh": {"default_user": base.get("ssh_user", "")},
        "webapp-runtime": {
            "web_port": base.get("web_port", ""),
            "api_port": base.get("api_port", ""),
        },
        "health-endpoint": {
            "health_path": base.get("web_health_path", ""),
            "smoke_paths": base.get("web_smoke_paths", ""),
        },
        "ephemeral-env": {
            "ttl_hours": base.get("ephemeral_ttl_hours", ""),
            "web_base_port": base.get("port_base", ""),
            "api_base_port": base.get("api_port_base", ""),
            "port_range": base.get("port_range", ""),
        },
    }
    env = RendererEnvironmentSettings(
        id=f"{project}-production",
        name="production",
        settings=env_settings,
    )
    return ProjectRendererSettings(
        project=project,
        deploy_namespace=project,
        display_name=base.get("project_display_name", project.title()),
        site_id=f"{project}-site",
        site_settings=site_settings,
        primary_environment=env,
        environments=(env,),
        capabilities=capabilities,
    )


def _stub_renderer_settings(
    monkeypatch, project: str, context: dict | None = None, base: dict | None = None,
) -> ProjectRendererSettings:
    settings = _settings_from_context(project, context, base)
    for module in (
        project_renderer_pulumi,
        project_renderer_pulumi_context,
        project_renderer_pulumi_instances,
    ):
        monkeypatch.setattr(
            module,
            "load_project_renderer_settings",
            lambda _project: settings,
        )
    return settings


class TestGatherPulumiValues:
    def test_returns_expected_keys(self, tmp_path, monkeypatch):
        context = {
            "domainName": "test.example.com",
            "originHost": "origin.example.com",
            "projectName": "buzz",
            "hostedZoneId": "Z123",
            "certificateArn": "arn:aws:acm:us-east-1:123:cert/abc",
            "originId": "buzzinfraDistributionOrigin18BAD744B",
            "distributionBucketName": "buzz-distribution-prod",
            "vpsInstanceType": "t3.small",
            "vpsRootVolumeGb": "20",
            "vpsSshKeyName": "buzz-key",
            "vpsIamInstanceProfileName": "buzz-origin-profile",
            "awsAccountId": "111122223333",
            "awsRegion": "us-east-1",
            "kmsKeyAlias": "alias/buzz-state",
            "stateBucket": "buzz-state",
            "pulumiInfraStackName": "buzz-infra",
            "pulumiVpsStackName": "buzz-vps",
        }
        _stub_renderer_settings(monkeypatch, "buzz", context)
        root = _make_project_root(tmp_path, "buzz")
        result = project_renderer_pulumi.gather_pulumi_values("buzz", root)

        expected = (
            _GATHER_VALUES_KEYS | _VPS_KEYS | _PULUMI_KEYS | _CI_KEYS
            | _RUNNER_FLEET_KEYS
        )
        assert set(result.keys()) == expected
        assert result["vps_iam_instance_profile_name"] == "buzz-origin-profile"
        assert result["origin_id"] == "buzzinfraDistributionOrigin18BAD744B"
        assert result["distribution_bucket_name"] == "buzz-distribution-prod"
        assert result["domain_txt_records_json"] == "[]"
        assert result["domain_mx_records_json"] == "[]"
        # No `github` capability in this context -> CI federation renders off.
        assert result["github_repo_slug"] == ""
        assert result["github_api_url"] == "https://api.github.com"
        assert result["manage_github_oidc_provider"] == "true"
        assert result["runner_fleet_instance_type"] == "m7g.2xlarge"
        assert result["runner_fleet_root_volume_gb"] == "200"

    def test_camelcase_to_snakecase_map(self, tmp_path, monkeypatch):
        context = {
            "vpsInstanceType": "t3.medium",
            "vpsRootVolumeGb": "40",
            "vpsSshKeyName": "buzz-prod",
            "vpsIamInstanceProfileName": "buzz-prod-origin",
            "awsAccountId": "999988887777",
            "awsRegion": "us-west-2",
            "kmsKeyAlias": "alias/buzz-pulumi",
            "stateBucket": "buzz-pulumi-state",
        }
        _stub_renderer_settings(monkeypatch, "buzz", context)
        root = _make_project_root(tmp_path, "buzz")
        result = project_renderer_pulumi.gather_pulumi_values("buzz", root)

        assert result["vps_instance_type"] == "t3.medium"
        assert result["vps_root_volume_gb"] == "40"
        assert result["vps_ssh_key_name"] == "buzz-prod"
        assert result["vps_iam_instance_profile_name"] == "buzz-prod-origin"
        # aws_account_id and aws_region live on gather_values()'s 25-key dict;
        # gather_pulumi_values keeps those base renderer slots while projecting
        # Pulumi-specific settings into the snake_case keys below.
        assert "aws_account_id" in result
        assert "aws_region" in result
        assert result["kms_key_alias"] == "alias/buzz-pulumi"
        assert result["state_bucket"] == "buzz-pulumi-state"

    def test_defaults_when_optional_fields_missing(self, tmp_path, monkeypatch):
        # Minimal context: omit the Pulumi-specific fields.
        context = {"projectName": "buzz"}
        _stub_renderer_settings(monkeypatch, "buzz", context)
        root = _make_project_root(tmp_path, "buzz")
        result = project_renderer_pulumi.gather_pulumi_values("buzz", root)

        assert result["pulumi_infra_stack_name"] == "buzz-infra"
        assert result["pulumi_vps_stack_name"] == "buzz-vps"
        assert result["pulumi_runner_fleet_stack_name"] == "buzz-runner-fleet"
        assert result["kms_key_alias"] == "alias/buzz-pulumi-state"
        assert result["state_bucket"] == "buzz-pulumi-state"
        # origin_id has no template-level default — empty string when
        # context omits it, so callers fail loud at render time rather
        # than silently inheriting another project's Id.
        assert result["origin_id"] == ""
        assert result["distribution_bucket_name"] == ""

    def test_domain_dns_records_serialize_from_site_settings(
        self, tmp_path, monkeypatch,
    ):
        context = {
            "projectName": "yoke",
            "txtRecords": [
                {
                    "id": "googleWorkspaceVerification",
                    "name": "@",
                    "value": "google-site-verification=abc123",
                    "ttl": 300,
                }
            ],
            "mxRecords": [
                {
                    "id": "googleWorkspaceGmail",
                    "name": "@",
                    "priority": 1,
                    "value": "SMTP.GOOGLE.COM",
                    "ttl": 300,
                }
            ],
        }
        _stub_renderer_settings(monkeypatch, "yoke", context)
        root = _make_project_root(tmp_path, "yoke")
        result = project_renderer_pulumi.gather_pulumi_values("yoke", root)

        assert result["domain_txt_records_json"] == (
            '[{"id":"googleWorkspaceVerification","name":"@",'
            '"value":"google-site-verification=abc123","ttl":300}]'
        )
        assert result["domain_mx_records_json"] == (
            '[{"id":"googleWorkspaceGmail","name":"@","priority":1,'
            '"value":"SMTP.GOOGLE.COM","ttl":300}]'
        )


class TestRenderPulumiStackYaml:
    def test_substitutes_stack_template_placeholders(self, tmp_path):
        template = tmp_path / "Pulumi.stack.yaml.tmpl"
        template.write_text(
            "config:\n"
            "  aws:region: {{aws_region}}\n"
            "  webapp-infra:aws_account_id: \"{{aws_account_id}}\"\n"
            "  webapp-infra:kms_key_alias: {{kms_key_alias}}\n"
            "  webapp-infra:domain_name: {{domain_name}}\n"
            "  webapp-infra:origin_host: {{origin_host}}\n"
            "  webapp-infra:project_name: {{project_name}}\n"
            "  webapp-infra:hosted_zone_id: {{hosted_zone_id}}\n"
            "  webapp-infra:certificate_arn: {{certificate_arn}}\n"
            "  webapp-infra:origin_id: {{origin_id}}\n"
            "  webapp-infra:distribution_bucket_name: {{distribution_bucket_name}}\n"
            "  webapp-infra:domain_txt_records: '{{domain_txt_records_json}}'\n"
            "  webapp-infra:domain_mx_records: '{{domain_mx_records_json}}'\n"
            "  webapp-infra:vps_instance_type: {{vps_instance_type}}\n"
            "  webapp-infra:vps_root_volume_gb: \"{{vps_root_volume_gb}}\"\n"
            "  webapp-infra:vps_ssh_key_name: {{vps_ssh_key_name}}\n"
            "  webapp-infra:vps_iam_instance_profile_name: "
            "{{vps_iam_instance_profile_name}}\n"
        )
        values = {
            "aws_region": "us-east-1",
            "aws_account_id": "111122223333",
            "kms_key_alias": "alias/buzz-state",
            "domain_name": "buzz.example.com",
            "origin_host": "origin.example.com",
            "project_name": "buzz",
            "hosted_zone_id": "Z123",
            "certificate_arn": "arn:aws:acm:us-east-1:123:cert/abc",
            "origin_id": "buzzinfraDistributionOrigin18BAD744B",
            "distribution_bucket_name": "buzz-distribution-prod",
            "domain_txt_records_json": "[]",
            "domain_mx_records_json": "[]",
            "vps_instance_type": "t3.small",
            "vps_root_volume_gb": "20",
            "vps_ssh_key_name": "buzz-key",
            "vps_iam_instance_profile_name": "buzz-origin-profile",
        }
        rendered = project_renderer_pulumi.render_pulumi_stack_yaml(
            template, values,
        )
        # No unsubstituted placeholders remain.
        assert "{{" not in rendered
        assert "}}" not in rendered
        # Spot-check substitutions landed.
        assert "us-east-1" in rendered
        assert "111122223333" in rendered
        assert "alias/buzz-state" in rendered
        assert "t3.small" in rendered
        assert "buzzinfraDistributionOrigin18BAD744B" in rendered
        assert "buzz-distribution-prod" in rendered
