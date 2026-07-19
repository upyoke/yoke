"""Tests for additive Pulumi environment stack instances."""

from __future__ import annotations


import pytest

from yoke_core.domain import project_renderer_pulumi
from yoke_core.domain import project_renderer_pulumi_instances
from yoke_core.domain.project_renderer_pulumi_instances import (
    PulumiStackInstance,
    gather_pulumi_stack_instances,
    instance_template_values,
)
from yoke_core.domain.project_renderer_runner_deployment_network import (
    STANDALONE_VPS_ELASTIC_IP_OUTPUT,
    STANDALONE_VPS_SECURITY_GROUP_OUTPUT,
)
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)
from runtime.api.domain.test_project_renderer_pulumi import _settings_from_context


def _make_project_tree(tmp_path, project: str):
    root = tmp_path / "repo"
    infra = root / "infra"
    infra.mkdir(parents=True)
    (infra / "Pulumi.yaml").write_text("name: webapp-infra\nruntime:\n  name: python\n")
    (infra / "Pulumi.stack.yaml.tmpl").write_text(
        "config:\n  aws:region: {{aws_region}}\n"
        "  webapp-infra:project_name: {{project_name}}\n"
    )
    (infra / "Pulumi.domain-stack.yaml.tmpl").write_text(
        "config:\n  aws:region: {{aws_region}}\n"
        "  webapp-infra:project_name: {{project_name}}\n"
        "  webapp-infra:domain_name: {{domain_name}}\n"
        "  webapp-infra:import_zone_id: {{import_zone_id}}\n"
        '  webapp-infra:manage_registration: "{{manage_registration}}"\n'
        "  webapp-infra:domain_txt_records: '{{domain_txt_records_json}}'\n"
        "  webapp-infra:domain_mx_records: '{{domain_mx_records_json}}'\n"
    )
    (infra / "Pulumi.environment-stack.yaml.tmpl").write_text(
        "config:\n"
        "  aws:region: {{aws_region}}\n"
        "  webapp-infra:stack_kind: environment\n"
        "  webapp-infra:stack_instance_name: {{stack_instance_name}}\n"
        "  webapp-infra:project_name: {{project_name}}\n"
        "  webapp-infra:environment: {{environment}}\n"
        "  webapp-infra:capabilities: {{capabilities}}\n"
        "  webapp-infra:domain_name: {{domain_name}}\n"
        "  webapp-infra:api_host: {{api_host}}\n"
        "  webapp-infra:origin_host: {{origin_host}}\n"
        "  webapp-infra:hosted_zone_id: {{hosted_zone_id}}\n"
        '  webapp-infra:api_origin_port: "{{api_origin_port}}"\n'
        "  webapp-infra:distribution_bucket_name: {{distribution_bucket_name}}\n"
        "  webapp-infra:distribution_origin_id: {{distribution_origin_id}}\n"
        "  webapp-infra:distribution_base_url: {{distribution_base_url}}\n"
        "  webapp-infra:distribution_repository_variable_namespace: "
        "{{distribution_repository_variable_namespace}}\n"
        "  webapp-infra:github_repo: {{github_repo_slug}}\n"
        "  webapp-infra:github_api_url: {{github_api_url}}\n"
        "  webapp-infra:origin_vps_stack_name: {{origin_vps_stack_name}}\n"
        "  webapp-infra:origin_vps_elastic_ip_output: "
        "{{origin_vps_elastic_ip_output}}\n"
        "  webapp-infra:origin_vps_security_group_output: "
        "{{origin_vps_security_group_output}}\n"
        "  webapp-infra:database_name: {{database_name}}\n"
        "  webapp-infra:database_master_username: {{database_master_username}}\n"
        "  webapp-infra:database_engine_version: {{database_engine_version}}\n"
        '  webapp-infra:database_min_capacity_acu: "{{database_min_capacity_acu}}"\n'
        '  webapp-infra:database_max_capacity_acu: "{{database_max_capacity_acu}}"\n'
        '  webapp-infra:database_seconds_until_auto_pause: "{{database_seconds_until_auto_pause}}"\n'
        '  webapp-infra:database_backup_retention_days: "{{database_backup_retention_days}}"\n'
        "  webapp-infra:database_allowed_security_group_ids: "
        "{{database_allowed_security_group_ids}}\n"
        "  webapp-infra:ephemeral_preview_domain: {{ephemeral_preview_domain}}\n"
        '  webapp-infra:github_app_private_key_secret_arn: '
        '"{{github_app_private_key_secret_arn}}"\n'
        '  webapp-infra:github_app_kms_key_arn: '
        '"{{github_app_kms_key_arn}}"\n'
        '  webapp-infra:render_only: "{{render_only}}"\n'
    )
    (infra / "__main__.py").write_text("# pulumi entrypoint\n")
    (infra / "webapp_infra_stack.py").write_text("# infra stack\n")
    (infra / "webapp_domain_stack.py").write_text("# domain stack\n")
    (infra / "webapp_dns_records.py").write_text("# dns helper\n")
    (infra / "webapp_vps_stack.py").write_text("# vps stack\n")
    (infra / "webapp_database_stack.py").write_text("# database stack\n")
    (infra / "webapp_api_stack.py").write_text("# api stack\n")
    (infra / "webapp_environment_stack.py").write_text("# environment stack\n")
    (infra / "webapp_distribution_stack.py").write_text("# distribution stack\n")
    (infra / "webapp_distribution_github_variables.py").write_text(
        "# distribution variables\n"
    )
    (infra / "webapp_environment_origin_policy.py").write_text("# origin policy\n")
    (infra / "webapp_github_repository_provider.py").write_text(
        "# github provider\n"
    )
    (infra / "requirements.txt").write_text("pulumi>=3.0.0\n")

    proj = root / "projects" / project
    proj.mkdir(parents=True)
    return root, proj


def _settings_with_environments(
    project: str,
    stacks: list[str],
    environments: list[RendererEnvironmentSettings],
) -> ProjectRendererSettings:
    base = _settings_from_context(
        project,
        {
            "projectName": project,
            "domainName": "example.com",
            "hostedZoneId": "ZHOSTEDZONE123",
            "stacks": stacks,
        },
    )
    return ProjectRendererSettings(
        project=base.project,
        deploy_namespace=base.deploy_namespace,
        display_name=base.display_name,
        site_id=base.site_id,
        site_settings=base.site_settings,
        primary_environment=environments[0] if environments else None,
        environments=tuple(environments),
        capabilities=base.capabilities,
    )


def _environment_settings(
    name: str,
    environment: str,
    *,
    render_only: bool = False,
) -> RendererEnvironmentSettings:
    host_prefix = "" if environment == "prod" else f"{environment}."
    activation_state = "render_only" if render_only else "active"
    return RendererEnvironmentSettings(
        id=f"yoke-api-{environment}",
        name=environment,
        settings={
            "hosts": {
                "api": f"api.{host_prefix}example.com",
                "origin": f"origin.{host_prefix}example.com",
                "origin_port": 80,
            },
            "database": {
                "name": f"yoke_{environment}",
                "master_username": "yoke_admin",
                "engine_version": "16.3",
                "min_capacity_acu": 0,
                "max_capacity_acu": 4,
                "backup_retention_days": 7,
                "allowed_security_group_ids": ["sg-tenant-provisioner"],
            },
            "pulumi": {
                "stack_name": name,
                "origin_vps_stack_name": f"{name}-origin",
                "activation_state": activation_state,
            },
            "servers": [{
                "instance_type": (
                    "t4g.medium" if environment == "prod" else "t4g.small"
                ),
                "root_volume_gb": 40 if environment == "prod" else 30,
                "aws_key_pair_name": f"yoke-{environment}",
                "iam_instance_profile_name": f"yoke-{environment}-host",
            }],
            "capabilities": ["database", "vps", "api"],
        },
    )


def _stub_settings(monkeypatch, settings: ProjectRendererSettings) -> None:
    monkeypatch.setattr(
        project_renderer_pulumi,
        "load_project_renderer_settings",
        lambda _project: settings,
    )
    monkeypatch.setattr(
        project_renderer_pulumi_instances,
        "load_project_renderer_settings",
        lambda _project: settings,
    )


class TestGatherPulumiStackInstances:
    def test_absent_stack_instances_returns_empty(self, tmp_path, monkeypatch):
        settings = _settings_with_environments("yoke", ["infra"], [])
        _stub_settings(monkeypatch, settings)
        root, _ = _make_project_tree(tmp_path, "yoke")

        assert gather_pulumi_stack_instances("yoke", root) == []

    def test_parses_stack_instances_and_template_values(self, tmp_path, monkeypatch):
        settings = _settings_with_environments(
            "yoke",
            ["domain"],
            [_environment_settings("yoke-prod", "prod", render_only=True)],
        )
        _stub_settings(monkeypatch, settings)
        root, _ = _make_project_tree(tmp_path, "yoke")

        instances = gather_pulumi_stack_instances("yoke", root)

        assert instances == [
            PulumiStackInstance(
                name="yoke-prod",
                environment="prod",
                capabilities=("database", "vps", "api"),
                config={
                    "api_host": "api.example.com",
                    "origin_host": "origin.example.com",
                    "hosted_zone_id": "ZHOSTEDZONE123",
                    "api_origin_port": "80",
                    "origin_vps_stack_name": "yoke-prod-origin",
                    "origin_vps_elastic_ip_output": (
                        STANDALONE_VPS_ELASTIC_IP_OUTPUT
                    ),
                    "origin_vps_security_group_output": (
                        STANDALONE_VPS_SECURITY_GROUP_OUTPUT
                    ),
                    "database_name": "yoke_prod",
                    "database_master_username": "yoke_admin",
                    "database_engine_version": "16.3",
                    "database_min_capacity_acu": "0",
                    "database_max_capacity_acu": "4",
                    "database_seconds_until_auto_pause": "1800",
                    "database_backup_retention_days": "7",
                    "database_allowed_security_group_ids": (
                        '["sg-tenant-provisioner"]'
                    ),
                    "distribution_bucket_name": "",
                    "distribution_origin_id": "",
                    "distribution_base_url": "",
                    "distribution_repository_variable_namespace": "",
                    "ephemeral_preview_domain": "",
                    "github_app_private_key_secret_arn": "",
                    "github_app_kms_key_arn": "",
                },
                render_only=True,
            )
        ]
        values = instance_template_values(
            instances[0],
            {"project_name": "yoke", "environment": "base"},
        )
        assert values["project_name"] == "yoke"
        assert values["environment"] == "prod"
        assert values["capabilities"] == "database,vps,api"
        assert values["render_only"] == "true"

    def test_ignores_environments_without_stack_name(self, tmp_path, monkeypatch):
        settings = _settings_with_environments(
            "yoke",
            ["domain"],
            [
                RendererEnvironmentSettings(
                    id="yoke-api-extra", name="extra", settings={}
                )
            ],
        )
        _stub_settings(monkeypatch, settings)
        root, _ = _make_project_tree(tmp_path, "yoke")

        assert gather_pulumi_stack_instances("yoke", root) == []

    def test_requires_origin_vps_stack_binding(self):
        environment = _environment_settings("yoke-prod", "prod")
        del environment.settings["pulumi"]["origin_vps_stack_name"]
        settings = _settings_with_environments("yoke", ["domain"], [environment])

        with pytest.raises(ValueError, match="origin_vps_stack_name"):
            project_renderer_pulumi_instances.pulumi_stack_instances_from_settings(
                settings
            )
