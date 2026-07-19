"""Tests for ephemeral preview-domain wiring in Pulumi stack instances.

Split from ``test_project_renderer_pulumi_instances.py`` (350-line cap):
covers the ``ephemeral-env`` capability's ``host_env``/``preview_domain``
resolution into the ``ephemeral_preview_domain`` stack-instance config key,
and the rendered environment-stack YAML carrying the key only for the host
environment's stack instance.
"""

from __future__ import annotations

import dataclasses

from yoke_core.domain import project_renderer_pulumi
from yoke_core.domain.project_renderer_pulumi_instances import (
    gather_pulumi_stack_instances,
)
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)
from runtime.api.domain.test_project_renderer_pulumi_instances import (
    _environment_settings,
    _make_project_tree,
    _settings_with_environments,
    _stub_settings,
)


def _settings_with_ephemeral_env(
    project: str,
    environments: list[RendererEnvironmentSettings],
    ephemeral: dict,
) -> ProjectRendererSettings:
    """Settings whose ``ephemeral-env`` capability carries *ephemeral*."""
    settings = _settings_with_environments(project, ["domain"], environments)
    capabilities = dict(settings.capabilities)
    capabilities["ephemeral-env"] = ephemeral
    return dataclasses.replace(settings, capabilities=capabilities)


class TestEphemeralPreviewDomainConfig:
    def test_host_environment_can_declare_domain_for_another_project(
        self,
        tmp_path,
        monkeypatch,
    ):
        stage = _environment_settings("platform-stage", "stage")
        stage = dataclasses.replace(
            stage,
            settings={**stage.settings, "previews": {"domain": "preview.example.com"}},
        )
        settings = _settings_with_environments("platform", ["domain"], [stage])
        _stub_settings(monkeypatch, settings)
        root, _ = _make_project_tree(tmp_path, "platform")

        instances = gather_pulumi_stack_instances("platform", root)

        assert instances[0].config["ephemeral_preview_domain"] == (
            "preview.example.com"
        )

    def test_host_env_instance_carries_preview_domain(self, tmp_path, monkeypatch):
        settings = _settings_with_ephemeral_env(
            "yoke",
            [
                _environment_settings("yoke-prod", "prod"),
                _environment_settings("yoke-stage", "stage"),
            ],
            {"host_env": "stage", "preview_domain": "preview.example.com"},
        )
        _stub_settings(monkeypatch, settings)
        root, _ = _make_project_tree(tmp_path, "yoke")

        instances = gather_pulumi_stack_instances("yoke", root)

        by_env = {instance.environment: instance for instance in instances}
        assert by_env["stage"].config["ephemeral_preview_domain"] == (
            "preview.example.com"
        )
        assert by_env["prod"].config["ephemeral_preview_domain"] == ""

    def test_missing_capability_yields_empty_preview_domain(
        self,
        tmp_path,
        monkeypatch,
    ):
        settings = _settings_with_environments(
            "yoke",
            ["domain"],
            [_environment_settings("yoke-prod", "prod")],
        )
        capabilities = dict(settings.capabilities)
        capabilities.pop("ephemeral-env", None)
        settings = dataclasses.replace(settings, capabilities=capabilities)
        _stub_settings(monkeypatch, settings)
        root, _ = _make_project_tree(tmp_path, "yoke")

        instances = gather_pulumi_stack_instances("yoke", root)

        assert instances[0].config["ephemeral_preview_domain"] == ""

    def test_capability_without_host_env_yields_empty_preview_domain(
        self,
        tmp_path,
        monkeypatch,
    ):
        settings = _settings_with_ephemeral_env(
            "yoke",
            [_environment_settings("yoke-prod", "prod")],
            {"preview_domain": "preview.example.com"},
        )
        _stub_settings(monkeypatch, settings)
        root, _ = _make_project_tree(tmp_path, "yoke")

        instances = gather_pulumi_stack_instances("yoke", root)

        assert instances[0].config["ephemeral_preview_domain"] == ""


class TestRenderEphemeralPreviewDomain:
    def test_renders_preview_domain_only_into_host_env_stack(
        self,
        tmp_path,
        monkeypatch,
    ):
        root, proj = _make_project_tree(tmp_path, "yoke")
        settings = _settings_with_ephemeral_env(
            "yoke",
            [
                _environment_settings("yoke-prod", "prod"),
                _environment_settings("yoke-stage", "stage"),
            ],
            {"host_env": "stage", "preview_domain": "preview.example.com"},
        )
        _stub_settings(monkeypatch, settings)
        values = {
            "aws_region": "us-east-1",
            "domain_name": "example.com",
            "project_name": "yoke",
            "github_repo_slug": "",
            "github_api_url": "https://api.github.com",
        }

        project_renderer_pulumi.render_pulumi_artifacts(
            "yoke",
            values,
            root,
            proj,
            write=True,
        )

        prod_yaml = (proj / "infra" / "Pulumi.yoke-prod.yaml").read_text()
        stage_yaml = (proj / "infra" / "Pulumi.yoke-stage.yaml").read_text()
        assert (
            "webapp-infra:ephemeral_preview_domain: preview.example.com" in stage_yaml
        )
        assert "webapp-infra:ephemeral_preview_domain:" in prod_yaml
        assert "preview.example.com" not in prod_yaml
        assert "{{" not in prod_yaml + stage_yaml
