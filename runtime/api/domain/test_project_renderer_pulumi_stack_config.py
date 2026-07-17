"""Stack-scoped Pulumi config projection tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

from yoke_core.domain.project_renderer_pulumi_stack_config import (
    build_pulumi_stack_config,
)
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)


def _environment(name: str) -> RendererEnvironmentSettings:
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
                "secrets_provider": f"awskms://alias/acme-{name}",
                "encrypted_key": f"encrypted-{name}",
            },
            "capabilities": ["api", "database"],
            "servers": {
                "instance_type": "t4g.micro",
                "root_volume_gb": 20,
                "aws_key_pair_name": f"acme-{name}",
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


def test_stack_config_projects_only_selected_environment(monkeypatch):
    production = _environment("production")
    stage = _environment("stage")
    settings = ProjectRendererSettings(
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
                "stacks": ["infra"],
                "stack_state": {
                    "acme-infra": {
                        "secrets_provider": "awskms://alias/acme-infra",
                        "encrypted_key": "encrypted-infra",
                    }
                },
            },
            "github": {
                "repo_owner": "acme",
                "repo_name": "app",
                "api_url": "https://api.github.com",
            },
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
        module,
        "read_github_state",
        lambda project, db_path, conn=None: SimpleNamespace(
            binding={
                "github_repo": "acme/app",
                "api_url": "https://api.github.com",
            }
        ),
    )

    payload = build_pulumi_stack_config(object(), "acme", "acme-stage")
    encoded = json.dumps(payload, sort_keys=True)
    assert payload["config_schema"] == 2
    assert payload["stack_kind"] == "environment"
    assert payload["render_values"]["origin_host"] == "origin.stage.acme.test"
    assert payload["operator_state"] == {
        "secrets_provider": "awskms://alias/acme-stage",
        "encrypted_key": "encrypted-stage",
    }
    assert "production" not in encoded
    assert "site_settings" not in payload
    assert "environments" not in payload
    assert "capabilities" not in payload
    assert payload["authority"]["github_permissions"] == {"metadata": "read"}


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
        module,
        "read_github_state",
        lambda *args, **kwargs: SimpleNamespace(binding=None),
    )
    stage_payload = build_pulumi_stack_config(object(), "acme", "acme-stage")
    prod_payload = build_pulumi_stack_config(
        object(), "acme", "acme-production"
    )
    assert stage_payload["operator_state"]["encrypted_key"] == "encrypted-stage"
    assert prod_payload["operator_state"]["encrypted_key"] == (
        "encrypted-production"
    )
