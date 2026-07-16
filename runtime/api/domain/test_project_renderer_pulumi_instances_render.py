"""Rendered-file coverage for DB-declared Pulumi stack instances."""

import pytest

from yoke_core.domain import project_renderer_pulumi
from yoke_core.domain import project_renderer_pulumi_instances
from runtime.api.domain.test_project_renderer_pulumi_instances import (
    _environment_settings,
    _make_project_tree,
    _settings_with_environments,
    _stub_settings,
)


def _render(tmp_path, monkeypatch, stacks, environments):
    root, project_root = _make_project_tree(tmp_path, "yoke")
    _stub_settings(
        monkeypatch,
        _settings_with_environments("yoke", stacks, environments),
    )
    project_renderer_pulumi.render_pulumi_artifacts(
        "yoke",
        {
            "aws_region": "us-east-1",
            "domain_name": "example.com",
            "project_name": "yoke",
            "github_repo_slug": "",
            "github_api_url": "https://api.github.com",
        },
        root,
        project_root,
        write=True,
    )
    return project_root / "infra"


def test_renders_instances_additively_with_legacy_stacks(tmp_path, monkeypatch):
    infra = _render(
        tmp_path,
        monkeypatch,
        ["infra"],
        [_environment_settings("yoke-prod", "prod")],
    )

    names = {path.name for path in infra.iterdir()}
    assert {
        "Pulumi.yoke-infra.yaml",
        "Pulumi.yoke-prod.yaml",
        "webapp_environment_stack.py",
        "webapp_database_stack.py",
        "webapp_api_stack.py",
        "webapp_vps_stack.py",
    } <= names
    stack_yaml = (infra / "Pulumi.yoke-prod.yaml").read_text()
    assert "webapp-infra:environment: prod" in stack_yaml
    assert "webapp-infra:capabilities: database,vps,api" in stack_yaml
    assert "webapp-infra:api_host: api.example.com" in stack_yaml
    assert "webapp-infra:origin_host: origin.example.com" in stack_yaml
    assert 'webapp-infra:database_min_capacity_acu: "0"' in stack_yaml
    assert 'webapp-infra:database_seconds_until_auto_pause: "1800"' in stack_yaml
    assert 'webapp-infra:render_only: "false"' in stack_yaml
    assert "vpc_id" not in stack_yaml
    assert "subnet_ids" not in stack_yaml
    assert (
        'webapp-infra:database_allowed_security_group_ids: ["sg-tenant-provisioner"]'
    ) in stack_yaml
    assert "{{" not in stack_yaml


def test_renders_prod_stage_and_preserves_legacy_domain_stack(tmp_path, monkeypatch):
    infra = _render(
        tmp_path,
        monkeypatch,
        ["domain"],
        [
            _environment_settings("yoke-prod", "prod"),
            _environment_settings("yoke-stage", "stage", render_only=True),
        ],
    )

    names = {path.name for path in infra.iterdir()}
    assert {
        "Pulumi.yoke-domain.yaml",
        "Pulumi.yoke-prod.yaml",
        "Pulumi.yoke-stage.yaml",
        "webapp_domain_stack.py",
        "webapp_environment_stack.py",
        "webapp_database_stack.py",
        "webapp_api_stack.py",
        "webapp_vps_stack.py",
    } <= names
    assert "Pulumi.yoke-infra.yaml" not in names
    assert "Pulumi.yoke-vps.yaml" not in names

    prod_yaml = (infra / "Pulumi.yoke-prod.yaml").read_text()
    stage_yaml = (infra / "Pulumi.yoke-stage.yaml").read_text()
    domain_yaml = (infra / "Pulumi.yoke-domain.yaml").read_text()
    assert "webapp-infra:stack_kind: environment" in prod_yaml
    assert "webapp-infra:api_host: api.example.com" in prod_yaml
    assert "webapp-infra:environment: stage" in stage_yaml
    assert "webapp-infra:api_host: api.stage.example.com" in stage_yaml
    assert 'webapp-infra:render_only: "true"' in stage_yaml
    assert 'webapp-infra:manage_registration: "false"' in domain_yaml
    assert "webapp-infra:api_host" not in domain_yaml
    assert "webapp-infra:database_engine_version" not in domain_yaml
    assert "{{" not in prod_yaml + stage_yaml + domain_yaml


def test_rejects_non_list_database_security_group_setting():
    environment = _environment_settings("yoke-prod", "prod")
    environment.settings["database"]["allowed_security_group_ids"] = (
        "sg-tenant-provisioner"
    )
    settings = _settings_with_environments("yoke", ["domain"], [environment])

    with pytest.raises(ValueError, match="database.allowed_security_group_ids"):
        project_renderer_pulumi_instances.pulumi_stack_instances_from_settings(settings)


def test_missing_database_security_group_setting_defaults_empty():
    environment = _environment_settings("yoke-prod", "prod")
    del environment.settings["database"]["allowed_security_group_ids"]
    settings = _settings_with_environments("yoke", ["domain"], [environment])

    (instance,) = (
        project_renderer_pulumi_instances.pulumi_stack_instances_from_settings(settings)
    )
    assert instance.config["database_allowed_security_group_ids"] == "[]"
