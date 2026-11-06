"""Tests for additive Pulumi environment stack instances."""

from __future__ import annotations

from runtime.api.domain.project_renderer_pulumi_instances_test_support import (
    _environment_settings as _environment_settings,
    _make_project_tree as _make_project_tree,
    _settings_with_environments as _settings_with_environments,
    _stub_settings as _stub_settings,
)


import pytest

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
    RendererEnvironmentSettings,
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
