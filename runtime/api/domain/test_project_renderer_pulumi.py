"""Tests for project_renderer_pulumi.py — Pulumi-specific rendering.

Covers the key-set contract for ``gather_pulumi_values``,
the camelCase-to-snake_case mapping, the stack-template substitution
contract on the stack template, and the seven-file output of
``render_pulumi_artifacts``.
"""

from __future__ import annotations

from runtime.api.domain.project_renderer_pulumi_test_support import (
    _make_project_root as _make_project_root,
    _settings_from_context as _settings_from_context,
    _stub_renderer_settings as _stub_renderer_settings,
)


from yoke_core.domain import project_renderer_pulumi

from runtime.api.domain.project_renderer_pulumi_keys_test_support import (
    _GATHER_VALUES_KEYS,
)

_VPS_KEYS = {
    "vps_instance_type",
    "vps_root_volume_gb",
    "vps_ssh_key_name",
    "vps_iam_instance_profile_name",
}
_PULUMI_KEYS = {
    "origin_id",
    "component_type_aliases_json",
    "distribution_bucket_name",
    "kms_key_alias",
    "state_bucket",
    "pulumi_infra_stack_name",
    "pulumi_vps_stack_name",
    "pulumi_runner_fleet_stack_name",
    "domain_txt_records_json",
    "domain_mx_records_json",
}
_CI_KEYS = {
    "delivery_authority_json",
    "delivery_cloudfront_distribution_ids_json",
    "delivery_distribution_bucket_names_json",
    "github_api_url",
    "github_app_private_key_secret_arns_json",
    "github_repo_slug",
    "manage_github_oidc_provider",
}
_RUNNER_FLEET_KEYS = {
    "runner_fleet_aws_capability",
    "runner_fleet_aws_region",
    "runner_fleet_github_capability",
    "runner_fleet_repo",
    "runner_fleet_labels_json",
    "runner_fleet_variable_name",
    "runner_fleet_routing_enabled",
    "runner_fleet_github_repo_owner",
    "runner_fleet_github_repo_name",
    "runner_fleet_github_installation_id",
    "runner_fleet_github_repository_id",
    "runner_fleet_github_app_issuer",
    "runner_fleet_github_api_url",
    "runner_fleet_github_web_url",
    "runner_fleet_github_private_key_secret_arn",
    "runner_fleet_token_broker_function",
    "runner_fleet_instance_type",
    "runner_fleet_architecture",
    "runner_fleet_root_volume_gb",
    "runner_fleet_runner_count",
    "runner_fleet_max_runner_count",
    "runner_fleet_idle_shutdown_minutes",
    "runner_fleet_shutdown_mode",
    "runner_fleet_lifecycle_writers_paused",
    "runner_fleet_lifecycle_code_frozen",
    "runner_fleet_spot_on_demand_base_capacity",
    "runner_fleet_spot_on_demand_percentage_above_base",
    "runner_fleet_deployment_ssh_stack_outputs_json",
}


class TestGatherPulumiValues:
    def test_returns_expected_keys(self, tmp_path, monkeypatch):
        context = {
            "domainName": "test.example.com",
            "originHost": "origin.example.com",
            "projectName": "externalwebapp",
            "hostedZoneId": "Z123",
            "certificateArn": "arn:aws:acm:us-east-1:123:cert/abc",
            "originId": "externalwebappinfraDistributionOrigin18BAD744B",
            "distributionBucketName": "externalwebapp-distribution-prod",
            "vpsInstanceType": "t3.small",
            "vpsRootVolumeGb": "20",
            "vpsSshKeyName": "externalwebapp-key",
            "vpsIamInstanceProfileName": "externalwebapp-origin-profile",
            "awsAccountId": "111122223333",
            "awsRegion": "us-east-1",
            "kmsKeyAlias": "alias/externalwebapp-state",
            "stateBucket": "externalwebapp-state",
            "pulumiInfraStackName": "externalwebapp-infra",
            "pulumiVpsStackName": "externalwebapp-vps",
        }
        _stub_renderer_settings(monkeypatch, "externalwebapp", context)
        root = _make_project_root(tmp_path, "externalwebapp")
        result = project_renderer_pulumi.gather_pulumi_values("externalwebapp", root)

        expected = (
            _GATHER_VALUES_KEYS
            | _VPS_KEYS
            | _PULUMI_KEYS
            | _CI_KEYS
            | _RUNNER_FLEET_KEYS
        )
        assert set(result.keys()) == expected
        assert (
            result["vps_iam_instance_profile_name"] == "externalwebapp-origin-profile"
        )
        assert result["origin_id"] == "externalwebappinfraDistributionOrigin18BAD744B"
        assert result["distribution_bucket_name"] == "externalwebapp-distribution-prod"
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
            "vpsSshKeyName": "externalwebapp-prod",
            "vpsIamInstanceProfileName": "externalwebapp-prod-origin",
            "awsAccountId": "999988887777",
            "awsRegion": "us-west-2",
            "kmsKeyAlias": "alias/externalwebapp-pulumi",
            "stateBucket": "externalwebapp-pulumi-state",
        }
        _stub_renderer_settings(monkeypatch, "externalwebapp", context)
        root = _make_project_root(tmp_path, "externalwebapp")
        result = project_renderer_pulumi.gather_pulumi_values("externalwebapp", root)

        assert result["vps_instance_type"] == "t3.medium"
        assert result["vps_root_volume_gb"] == "40"
        assert result["vps_ssh_key_name"] == "externalwebapp-prod"
        assert result["vps_iam_instance_profile_name"] == "externalwebapp-prod-origin"
        # aws_account_id and aws_region live on gather_values()'s 25-key dict;
        # gather_pulumi_values keeps those base renderer slots while projecting
        # Pulumi-specific settings into the snake_case keys below.
        assert "aws_account_id" in result
        assert "aws_region" in result
        assert result["kms_key_alias"] == "alias/externalwebapp-pulumi"
        assert result["state_bucket"] == "externalwebapp-pulumi-state"

    def test_defaults_when_optional_fields_missing(self, tmp_path, monkeypatch):
        # Minimal context: omit the Pulumi-specific fields.
        context = {"projectName": "externalwebapp"}
        _stub_renderer_settings(monkeypatch, "externalwebapp", context)
        root = _make_project_root(tmp_path, "externalwebapp")
        result = project_renderer_pulumi.gather_pulumi_values("externalwebapp", root)

        assert result["pulumi_infra_stack_name"] == "externalwebapp-infra"
        assert result["pulumi_vps_stack_name"] == "externalwebapp-vps"
        assert result["pulumi_runner_fleet_stack_name"] == "externalwebapp-runner-fleet"
        assert result["kms_key_alias"] == "alias/externalwebapp-pulumi-state"
        assert result["state_bucket"] == "externalwebapp-pulumi-state"
        # origin_id has no template-level default — empty string when
        # context omits it, so callers fail loud at render time rather
        # than silently inheriting another project's Id.
        assert result["origin_id"] == ""
        assert result["distribution_bucket_name"] == ""

    def test_domain_dns_records_serialize_from_site_settings(
        self,
        tmp_path,
        monkeypatch,
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
