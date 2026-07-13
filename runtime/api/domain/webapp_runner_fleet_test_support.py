"""Shared Pulumi mock assembly for runner-fleet template tests."""

from __future__ import annotations

import hashlib
import json
import os
import types

from runtime.api.domain.test_webapp_registry_stack import (
    _Recorder,
    _load_template_module,
    _make_resource_class,
)


_REPOSITORY_TOKEN = "github_pat_short_lived_repository_test"
_PRIVATE_KEY_SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:yoke-github-app-AbCdEf"
)


def _authority_envelope(authority):
    canonical = json.dumps(authority, sort_keys=True, separators=(",", ":"))
    return json.dumps(
        {
            "schema": 1,
            "authority": authority,
            "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        },
        separators=(",", ":"),
    )


def _runner_stack(
    monkeypatch,
    *,
    shutdown_mode="terminate",
    runner_count=1,
    max_count=1,
    repository_token=_REPOSITORY_TOKEN,
    github_provider_token=_REPOSITORY_TOKEN,
    github_api_url="https://api.github.com",
    github_web_url="https://github.com",
    aws_capability="aws-admin",
    aws_region="us-east-1",
    stack_name="yoke-runner-fleet",
    routing_enabled=True,
    authority_overrides=None,
    config_overrides=None,
    stack_reference_outputs=None,
    recorder=None,
):
    recorder = recorder or _Recorder()
    recorder.stack_outputs = stack_reference_outputs or {
        "yoke-prod": {"originElasticIpAddress": "203.0.113.10"},
        "yoke-stage": {"originElasticIpAddress": "203.0.113.11"},
    }
    if repository_token is None:
        monkeypatch.delenv("RUNNER_FLEET_GITHUB_TOKEN", raising=False)
    else:
        monkeypatch.setenv("RUNNER_FLEET_GITHUB_TOKEN", repository_token)
    if github_provider_token is None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    else:
        monkeypatch.setenv("GITHUB_TOKEN", github_provider_token)
    host_cycle = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_runner_host_cycle.py",
    )
    internals = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_runner_fleet_internals.py",
        extra_modules={"webapp_runner_host_cycle": host_cycle},
    )
    github_state = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_runner_github_state.py",
    )
    broker_stack = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_runner_github_broker_stack.py",
        extra_modules={"webapp_runner_github_state": github_state},
    )
    iam = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_runner_fleet_iam.py",
        extra_modules={"webapp_runner_fleet_internals": internals},
    )
    network = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_runner_fleet_network.py",
    )
    pulumi_random = types.ModuleType("pulumi_random")
    pulumi_random.RandomPassword = _make_resource_class(
        recorder,
        "random:index:RandomPassword",
    )
    pulumi_github = types.ModuleType("pulumi_github")
    provider_class = _make_resource_class(
        recorder,
        "pulumi:providers:github",
    )

    class _EnvReadingProvider(provider_class):
        def __init__(self, resource_name, opts=None, **kwargs):
            ambient_token = os.environ.get("GITHUB_TOKEN")
            if ambient_token is not None:
                kwargs["token"] = ambient_token
            super().__init__(resource_name, opts=opts, **kwargs)
            self.constructor_github_token = ambient_token

    pulumi_github.Provider = _EnvReadingProvider
    pulumi_github.RepositoryWebhook = _make_resource_class(
        recorder,
        "github:index/repositoryWebhook:RepositoryWebhook",
    )
    pulumi_github.ActionsVariable = _make_resource_class(
        recorder,
        "github:index/actionsVariable:ActionsVariable",
    )
    github_provider = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_github_repository_provider.py",
        extra_modules={"pulumi_github": pulumi_github},
    )
    github_webhook = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_runner_github_webhook.py",
        extra_modules={
            "pulumi_github": pulumi_github,
            "webapp_github_repository_provider": github_provider,
        },
    )
    authority_intent = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_runner_authority_intent.py",
    )
    fleet_config = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_runner_fleet_config.py",
    )
    module = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_runner_fleet_stack.py",
        extra_modules={
            "webapp_runner_fleet_internals": internals,
            "webapp_runner_fleet_config": fleet_config,
            "webapp_runner_fleet_iam": iam,
            "webapp_runner_fleet_network": network,
            "webapp_runner_authority_intent": authority_intent,
            "webapp_runner_github_broker_stack": broker_stack,
            "webapp_runner_github_webhook": github_webhook,
            "pulumi_random": pulumi_random,
        },
    )
    module.pulumi.get_stack = lambda: stack_name
    args = module.WebappRunnerFleetArgs(
        project="yoke",
        deploy_namespace="yoke",
        aws_capability=aws_capability,
        aws_region=aws_region,
        github_capability="github",
        github_app_environment="yoke-api-stage",
        github_repo="upyoke/yoke",
        github_repo_owner="upyoke",
        github_repo_name="yoke",
        github_installation_id="123456",
        github_repository_id="789012",
        github_app_issuer="Iv1.runner-fleet",
        github_api_url=github_api_url,
        github_web_url=github_web_url,
        github_private_key_secret_arn=_PRIVATE_KEY_SECRET_ARN,
        runner_labels=[
            "self-hosted",
            "Linux",
            "ARM64",
            "yoke-github-actions",
        ],
        runner_variable_name="YOKE_LINUX_RUNS_ON",
        routing_enabled=routing_enabled,
        runner_count=runner_count,
        max_runner_count=max_count,
        instance_type="m7g.2xlarge",
        architecture="arm64",
        root_volume_gb=100,
        idle_shutdown_minutes=30,
        shutdown_mode=shutdown_mode,
        deployment_ssh_stack_outputs={
            "yoke-prod": "originElasticIpAddress",
            "yoke-stage": "originElasticIpAddress",
        },
    )
    for key, value in (config_overrides or {}).items():
        setattr(args, key, value)
    authority = {
        "project": args.project,
        "deploy_namespace": args.deploy_namespace,
        "stack_name": "yoke-runner-fleet",
        "aws_capability": args.aws_capability,
        "aws_region": args.aws_region,
        "github_capability": args.github_capability,
        "github_app_environment": args.github_app_environment,
        "repo": args.github_repo,
        "repo_owner": args.github_repo_owner,
        "repo_name": args.github_repo_name,
        "installation_id": args.github_installation_id,
        "repository_id": args.github_repository_id,
        "app_issuer": args.github_app_issuer,
        "api_url": args.github_api_url,
        "web_url": args.github_web_url,
        "private_key_secret_arn": args.github_private_key_secret_arn,
        "runner_labels": list(args.runner_labels),
        "runner_variable_name": args.runner_variable_name,
        "routing_enabled": args.routing_enabled,
        "runner_count": args.runner_count,
        "max_runner_count": args.max_runner_count,
        "instance_type": args.instance_type,
        "architecture": args.architecture,
        "root_volume_gb": args.root_volume_gb,
        "idle_shutdown_minutes": args.idle_shutdown_minutes,
        "shutdown_mode": args.shutdown_mode,
        "deployment_ssh_stack_outputs": dict(
            args.deployment_ssh_stack_outputs
        ),
    }
    authority.update(authority_overrides or {})
    monkeypatch.setenv(
        authority_intent.AUTHORITY_INTENT_ENV,
        _authority_envelope(authority),
    )
    stack = module.WebappRunnerFleetStack("yoke-runner-fleet", args)
    return recorder, stack


__all__ = ["_REPOSITORY_TOKEN", "_runner_stack"]
