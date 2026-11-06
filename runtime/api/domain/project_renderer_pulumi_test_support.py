# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import project_renderer_pulumi

from yoke_core.domain import project_renderer_pulumi_context

from yoke_core.domain import project_renderer_pulumi_instances

from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)

from runtime.api.domain.project_renderer_pulumi_keys_test_support import (
    _GATHER_VALUES_KEYS,
)


def _make_project_root(tmp_path: Path, project: str) -> Path:
    """Build a minimal project tree."""
    root = tmp_path / "repo"
    proj = root / "projects" / project
    proj.mkdir(parents=True)
    (proj / "config").write_text("aws_region=us-east-1\n")
    return root


def _settings_from_context(
    project: str,
    context: dict | None = None,
    base: dict | None = None,
) -> ProjectRendererSettings:
    """Build a small DB-settings snapshot for Pulumi unit tests."""
    context = context or {}
    base = base or {}
    domain = {
        "domain_name": base.get("domain_name", context.get("domainName", "")),
        "hosted_zone_id": base.get("hosted_zone_id", context.get("hostedZoneId", "")),
        "certificate_arn": base.get(
            "certificate_arn",
            context.get("certificateArn", ""),
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
            "distribution_bucket_name": context.get("distributionBucketName", ""),
            "distribution_id": base.get("cloudfront_id", ""),
            "distribution_domain": base.get("cloudfront_domain", ""),
        },
    }
    env_settings = {
        "hosts": {"origin": base.get("origin_host", context.get("originHost", ""))},
        "servers": [
            {
                "host": base.get("origin_ip", ""),
                "instance_type": context.get("vpsInstanceType", ""),
                "root_volume_gb": context.get("vpsRootVolumeGb", ""),
                "aws_key_pair_name": context.get("vpsSshKeyName", ""),
                "iam_instance_profile_name": context.get(
                    "vpsIamInstanceProfileName", ""
                ),
            }
        ],
    }
    capabilities = {
        "aws-admin": {
            "region": base.get("aws_region", context.get("awsRegion", "us-east-1")),
            "account_id": base.get(
                "aws_account_id",
                context.get("awsAccountId", ""),
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
            "preview_domain": base.get("preview_domain", ""),
            "preview_namespace": base.get("preview_namespace", ""),
            "route_base_port": base.get("preview_route_port_base", ""),
            "trigger": base.get("preview_trigger", "github-push"),
        },
    }
    env = RendererEnvironmentSettings(
        id=f"{project}-prod",
        name="prod",
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
    monkeypatch,
    project: str,
    context: dict | None = None,
    base: dict | None = None,
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
