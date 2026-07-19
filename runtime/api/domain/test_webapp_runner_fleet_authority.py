"""Authority refusal boundaries for the self-hosted runner Pack."""

import pytest

from runtime.api.domain.test_webapp_registry_stack import _Recorder
from runtime.api.domain.webapp_runner_fleet_test_support import _runner_stack


@pytest.mark.parametrize(
    ("config_overrides", "authority_overrides", "field"),
    [
        (
            {"github_api_url": "http://github.internal.example/api/v3"},
            {"api_url": "https://github.internal.example/api/v3"},
            "api_url",
        ),
        (
            {"github_api_url": "https://attacker.example/api/v3"},
            {"api_url": "https://api.github.com"},
            "api_url",
        ),
        (
            {
                "github_app_issuer": "Iv1.other",
                "github_installation_id": "999",
                "github_repository_id": "998",
            },
            {
                "app_issuer": "Iv1.runner-fleet",
                "installation_id": "123456",
                "repository_id": "789012",
            },
            "app_issuer",
        ),
        (
            {
                "github_capability": "other",
                "github_repo_owner": "other-org",
                "github_repo_name": "other-repo",
                "github_private_key_secret_arn": (
                    "arn:aws:secretsmanager:us-east-1:123456789012:"
                    "secret:other-app"
                ),
            },
            {
                "github_capability": "github",
                "repo_owner": "upyoke",
                "repo_name": "yoke",
                "private_key_secret_arn": (
                    "arn:aws:secretsmanager:us-east-1:123456789012:"
                    "secret:yoke-github-app-AbCdEf"
                ),
            },
            "github_capability",
        ),
        (
            {
                "runner_variable_name": "OTHER_ROUTE",
                "runner_labels": ["self-hosted", "Linux", "X64"],
                "routing_enabled": False,
            },
            {
                "runner_variable_name": "YOKE_LINUX_RUNS_ON",
                "runner_labels": [
                    "self-hosted", "Linux", "ARM64", "yoke-github-actions",
                ],
                "routing_enabled": True,
            },
            "runner_labels",
        ),
        (
            {
                "deployment_ssh_stack_outputs": {
                    "yoke-prod": "vpsElasticIpAddress",
                    "yoke-stage": "originElasticIpAddress",
                },
            },
            {
                "deployment_ssh_stack_outputs": {
                    "yoke-prod": "originElasticIpAddress",
                    "yoke-stage": "originElasticIpAddress",
                },
            },
            "deployment_ssh_stack_outputs",
        ),
        (
            {
                "aws_capability": "other-admin",
                "aws_region": "us-west-2",
                "instance_type": "c7i.16xlarge",
                "architecture": "x64",
                "root_volume_gb": 1000,
                "runner_count": 2,
                "max_runner_count": 2,
                "idle_shutdown_minutes": 5,
                "shutdown_mode": "stop",
            },
            {
                "aws_capability": "aws-admin",
                "aws_region": "us-east-1",
                "instance_type": "m7g.2xlarge",
                "architecture": "arm64",
                "root_volume_gb": 100,
                "runner_count": 1,
                "max_runner_count": 1,
                "idle_shutdown_minutes": 30,
                "shutdown_mode": "terminate",
            },
            "aws_region",
        ),
    ],
)
def test_authority_drift_refuses_before_github_provider_construction(
    monkeypatch, config_overrides, authority_overrides, field,
):
    recorder = _Recorder()

    with pytest.raises(RuntimeError, match=field):
        _runner_stack(
            monkeypatch,
            config_overrides=config_overrides,
            authority_overrides=authority_overrides,
            recorder=recorder,
        )

    assert recorder.resources == []


def test_wrong_pulumi_stack_refuses_before_resource_construction(monkeypatch):
    recorder = _Recorder()

    with pytest.raises(RuntimeError, match="stack_name"):
        _runner_stack(
            monkeypatch,
            stack_name="wrong-runner-state",
            authority_overrides={"stack_name": "yoke-runner-fleet"},
            recorder=recorder,
        )

    assert recorder.resources == []
