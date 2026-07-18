"""Stack-scoped Pulumi config projection tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain.project_renderer_pulumi_stack_config import (
    PulumiStackConfigError,
    build_pulumi_stack_config,
)
from yoke_core.domain.project_renderer_pulumi_scoped import (
    render_scoped_pulumi_config,
)
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)


def _environment(name: str) -> RendererEnvironmentSettings:
    is_production = name == "production"
    return RendererEnvironmentSettings(
        id=f"acme-{name}",
        name=name,
        settings={
            "hosts": {
                "api": f"api.{name}.acme.test",
                "origin": f"origin.{name}.acme.test",
                "origin_port": 8000,
            },
            "pulumi": {
                "stack_name": f"acme-{name}",
                "origin_vps_stack_name": f"acme-{name}-vps",
                "secrets_provider": f"awskms://alias/acme-{name}",
                "encrypted_key": f"encrypted-{name}",
            },
            "capabilities": ["api", "database"],
            "servers": {
                "instance_type": "t4g.small" if is_production else "t4g.micro",
                "root_volume_gb": 40 if is_production else 20,
                "aws_key_pair_name": f"acme-{name}",
                "iam_instance_profile_name": f"acme-{name}-host",
            },
            "database": {
                "name": f"acme_{name}",
                "master_username": "acme",
                "engine_version": "16.4",
                "min_capacity_acu": 0,
                "max_capacity_acu": 2,
                "allowed_security_group_ids": [],
            },
        },
    )


def _settings() -> ProjectRendererSettings:
    production = _environment("production")
    stage = _environment("stage")
    return ProjectRendererSettings(
        project="acme",
        deploy_namespace="acme",
        display_name="Acme",
        site_id="acme-site",
        site_settings={
            "domains": [{
                "domain_name": "acme.test",
                "hosted_zone_id": "ZACME",
            }]
        },
        primary_environment=production,
        environments=(production, stage),
        capabilities={
            "aws-admin": {
                "account_id": "123456789012",
                "region": "us-east-1",
            },
            "pulumi-state": {
                "state_bucket": "acme-pulumi-state",
                "kms_key_alias": "alias/acme-pulumi-state",
                "stacks": ["infra", "vps"],
                "vps_stack_name": "acme-production-vps",
                "stack_state": {
                    "acme-infra": {
                        "secrets_provider": "awskms://alias/acme-infra",
                        "encrypted_key": "encrypted-infra",
                    },
                    "acme-production-vps": {
                        "secrets_provider": "awskms://alias/acme-production-vps",
                        "encrypted_key": "encrypted-production-vps",
                    },
                    "acme-stage-vps": {
                        "secrets_provider": "awskms://alias/acme-stage-vps",
                        "encrypted_key": "encrypted-stage-vps",
                    },
                },
            },
            "github": {
                "repo_owner": "acme",
                "repo_name": "app",
                "api_url": "https://api.github.com",
            },
        },
    )


def _stub_settings(monkeypatch, settings: ProjectRendererSettings) -> None:
    from yoke_core.domain import project_renderer_pulumi_stack_config as module

    monkeypatch.setattr(
        module,
        "resolve_project",
        lambda conn, project, required=False: SimpleNamespace(id=7, slug="acme"),
    )
    monkeypatch.setattr(
        module, "_load_project_renderer_settings", lambda conn, project: settings
    )
    monkeypatch.setattr(
        module,
        "_github_binding_for_repo",
        lambda conn, repo, api: (
            "platform",
            {"github_repo": repo, "api_url": api},
        ),
    )


def test_stack_config_projects_only_selected_environment(monkeypatch):
    settings = _settings()
    _stub_settings(monkeypatch, settings)

    payload = build_pulumi_stack_config(object(), "acme", "acme-stage")
    encoded = json.dumps(payload, sort_keys=True)
    assert payload["config_schema"] == 2
    assert payload["stack_kind"] == "environment"
    assert payload["render_values"]["origin_host"] == "origin.stage.acme.test"
    assert payload["render_values"]["origin_vps_stack_name"] == "acme-stage-vps"
    assert payload["render_values"]["origin_vps_elastic_ip_output"] == (
        "vpsElasticIpAddress"
    )
    assert payload["render_values"]["origin_vps_security_group_output"] == (
        "vpsSecurityGroupId"
    )
    assert "vps_ssh_key_name" not in payload["render_values"]
    assert payload["operator_state"] == {
        "secrets_provider": "awskms://alias/acme-stage",
        "encrypted_key": "encrypted-stage",
    }
    assert "production" not in encoded
    assert "site_settings" not in payload
    assert "environments" not in payload
    assert "capabilities" not in payload
    assert payload["authority"]["github_project"] == "platform"
    assert payload["authority"]["github_permissions"] == {
        "metadata": "read",
        "actions_variables": "write",
    }


def test_selected_environment_ignores_unrelated_incomplete_vps(monkeypatch):
    settings = _settings()
    settings.primary_environment.settings["servers"] = {}
    _stub_settings(monkeypatch, settings)

    payload = build_pulumi_stack_config(object(), "acme", "acme-stage")

    assert payload["stack_kind"] == "environment"
    assert payload["render_values"]["environment"] == "stage"


def test_selected_vps_still_requires_its_server_inputs(monkeypatch):
    settings = _settings()
    settings.environments[1].settings["servers"] = {}
    _stub_settings(monkeypatch, settings)

    with pytest.raises(ValueError, match="servers.instance_type"):
        build_pulumi_stack_config(object(), "acme", "acme-stage-vps")


def test_stack_config_projects_component_type_aliases(monkeypatch):
    settings = _settings()
    aliases = {
        "infra": ["legacy:infra:EdgeStack"],
        "vps": ["legacy:infra:HostStack"],
    }
    settings.capabilities["pulumi-state"]["component_type_aliases"] = aliases
    _stub_settings(monkeypatch, settings)

    payload = build_pulumi_stack_config(object(), "acme", "acme-stage-vps")

    assert json.loads(
        payload["render_values"]["component_type_aliases_json"]
    ) == aliases


@pytest.mark.parametrize(
    ("stack", "instance_type", "root_volume_gb", "key_name", "encrypted_key"),
    [
        (
            "acme-production-vps",
            "t4g.small",
            "40",
            "acme-production",
            "encrypted-production-vps",
        ),
        (
            "acme-stage-vps",
            "t4g.micro",
            "20",
            "acme-stage",
            "encrypted-stage-vps",
        ),
    ],
)
def test_stack_config_projects_environment_declared_standalone_vps(
    monkeypatch,
    tmp_path,
    stack,
    instance_type,
    root_volume_gb,
    key_name,
    encrypted_key,
):
    _stub_settings(monkeypatch, _settings())

    payload = build_pulumi_stack_config(object(), "acme", stack)

    assert payload["stack_kind"] == "vps"
    assert payload["render_values"]["vps_instance_type"] == instance_type
    assert payload["render_values"]["vps_root_volume_gb"] == root_volume_gb
    assert payload["render_values"]["vps_ssh_key_name"] == key_name
    assert payload["render_values"]["vps_iam_instance_profile_name"] == (
        f"{key_name}-host"
    )
    assert payload["operator_state"]["encrypted_key"] == encrypted_key
    assert "environments" not in payload
    assert "site_settings" not in payload
    stack_path = render_scoped_pulumi_config(
        payload,
        project_root=Path(__file__).resolve().parents[3],
        output_dir=tmp_path / stack,
    )
    rendered = stack_path.read_text()
    assert f"webapp-infra:vps_instance_type: {instance_type}" in rendered
    assert f'webapp-infra:vps_root_volume_gb: "{root_volume_gb}"' in rendered
    assert f"webapp-infra:vps_ssh_key_name: {key_name}" in rendered


def test_stack_config_rejects_unknown_and_missing_vps_operator_state(monkeypatch):
    settings = _settings()
    _stub_settings(monkeypatch, settings)
    with pytest.raises(ValueError, match="is not declared"):
        build_pulumi_stack_config(object(), "acme", "acme-unknown-vps")

    del settings.capabilities["pulumi-state"]["stack_state"]["acme-stage-vps"]
    with pytest.raises(PulumiStackConfigError, match="operator state is missing"):
        build_pulumi_stack_config(object(), "acme", "acme-stage-vps")


def test_stack_config_separates_environment_operator_state(monkeypatch):
    production = _environment("production")
    stage = _environment("stage")
    settings = ProjectRendererSettings(
        project="acme",
        deploy_namespace="acme",
        display_name="Acme",
        site_id="acme-site",
        site_settings={"domains": [{"domain_name": "acme.test"}]},
        primary_environment=production,
        environments=(production, stage),
        capabilities={
            "aws-admin": {"region": "us-east-1"},
            "pulumi-state": {"state_bucket": "acme-state", "stacks": ["infra"]},
        },
    )
    from yoke_core.domain import project_renderer_pulumi_stack_config as module

    monkeypatch.setattr(
        module,
        "resolve_project",
        lambda conn, project, required=False: SimpleNamespace(id=7, slug="acme"),
    )
    monkeypatch.setattr(
        module, "_load_project_renderer_settings", lambda conn, project: settings
    )
    monkeypatch.setattr(
        module, "_github_binding_for_repo", lambda *args: ("", {})
    )
    stage_payload = build_pulumi_stack_config(object(), "acme", "acme-stage")
    prod_payload = build_pulumi_stack_config(
        object(), "acme", "acme-production"
    )
    assert stage_payload["operator_state"]["encrypted_key"] == "encrypted-stage"
    assert prod_payload["operator_state"]["encrypted_key"] == (
        "encrypted-production"
    )
