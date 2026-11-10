"""Shared Acme renderer settings for stack-scoped Pulumi config tests."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)


def acme_environment(name: str) -> RendererEnvironmentSettings:
    is_protected = name == "prod"
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
                "instance_type": "t4g.small" if is_protected else "t4g.micro",
                "root_volume_gb": 40 if is_protected else 20,
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


def acme_settings() -> ProjectRendererSettings:
    prod = acme_environment("prod")
    stage = acme_environment("stage")
    return ProjectRendererSettings(
        project="acme",
        deploy_namespace="acme",
        display_name="Acme",
        site_id="acme-site",
        site_settings={
            "domains": [
                {
                    "domain_name": "acme.test",
                    "hosted_zone_id": "ZACME",
                }
            ]
        },
        primary_environment=prod,
        environments=(prod, stage),
        capabilities={
            "aws-admin": {
                "account_id": "123456789012",
                "region": "us-east-1",
            },
            "pulumi-state": {
                "state_bucket": "acme-pulumi-state",
                "kms_key_alias": "alias/acme-pulumi-state",
                "stacks": ["infra", "vps"],
                "vps_stack_name": "acme-prod-vps",
                "stack_state": {
                    "acme-infra": {
                        "secrets_provider": "awskms://alias/acme-infra",
                        "encrypted_key": "encrypted-infra",
                    },
                    "acme-prod-vps": {
                        "secrets_provider": "awskms://alias/acme-prod-vps",
                        "encrypted_key": "encrypted-prod-vps",
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


def stub_acme_settings(monkeypatch, settings: ProjectRendererSettings) -> None:
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


__all__ = ["acme_environment", "acme_settings", "stub_acme_settings"]
