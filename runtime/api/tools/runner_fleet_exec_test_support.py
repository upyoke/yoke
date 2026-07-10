"""Shared fixtures for runner-fleet credential-bound process tests."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import json_helper


_SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:123456789012:"
    "secret:yoke-github-app-AbCdEf"
)
_PRIVATE_KEY = (
    "-----BEGIN PRIVATE KEY-----\n"
    "PRIVATE_KEY_MATERIAL\n"
    "-----END PRIVATE KEY-----\n"
)
_TOKEN = "ghs_repository_scoped_token"


class _ChunkedStream:
    def __init__(self, chunks):
        self._chunks = [
            chunk.encode("utf-8") if isinstance(chunk, str) else chunk
            for chunk in chunks
        ]
        self.closed = False

    def read(self, size):
        del size
        return self._chunks.pop(0) if self._chunks else b""

    def close(self):
        self.closed = True


class _Process:
    def __init__(self, *, stdout=(), stderr=(), returncode=0):
        self.stdout = _ChunkedStream(stdout)
        self.stderr = _ChunkedStream(stderr)
        self._returncode = returncode

    def wait(self):
        return self._returncode


def _write_snapshot(
    path: Path,
    *,
    project: str = "buzz",
    envelope_project: str | None = None,
    region: str | None = "us-east-1",
    aws_capability: str = "aws-admin",
    stack_name: str | None = None,
    schema: int = 1,
) -> Path:
    capabilities: dict[str, object] = {}
    if region is not None:
        capabilities[aws_capability] = {"region": region}
    runner_settings = {
        "github_capability": "github",
        "github_app_environment": "buzz-api-stage",
    }
    if aws_capability != "aws-admin":
        runner_settings["aws_capability"] = aws_capability
    capabilities["github-actions-runner-fleet"] = runner_settings
    payload = {
        "config_schema": schema,
        "project_id": 42,
        "project_slug": envelope_project or project,
        "renderer_settings": {
            "project": project,
            "deploy_namespace": project,
            "display_name": project.title(),
            "site_id": f"{project}-site",
            "site_settings": (
                {"pulumi": {"pulumiRunnerFleetStackName": stack_name}}
                if stack_name is not None
                else {}
            ),
            "environments": [],
            "capabilities": capabilities,
        },
    }
    json_helper.dump_path(path, payload)
    return path


def _runner_values(*, routing_enabled: bool = True) -> dict[str, str]:
    return {
        "runner_fleet_aws_capability": "aws-admin",
        "runner_fleet_aws_region": "us-east-1",
        "runner_fleet_github_capability": "github",
        "runner_fleet_github_app_environment": "buzz-api-stage",
        "runner_fleet_repo": "upyoke/yoke",
        "runner_fleet_github_repo_owner": "upyoke",
        "runner_fleet_github_repo_name": "yoke",
        "runner_fleet_github_private_key_secret_arn": _SECRET_ARN,
        "runner_fleet_github_app_issuer": "Iv1.runner-fleet",
        "runner_fleet_github_installation_id": "123456",
        "runner_fleet_github_repository_id": "789012",
        "runner_fleet_github_api_url": "https://api.github.com",
        "runner_fleet_github_web_url": "https://github.com",
        "runner_fleet_routing_enabled": (
            "true" if routing_enabled else "false"
        ),
        "runner_fleet_labels_json": (
            '["self-hosted","Linux","ARM64","yoke-github-actions"]'
        ),
        "runner_fleet_variable_name": "YOKE_LINUX_RUNS_ON",
        "runner_fleet_runner_count": "1",
        "runner_fleet_max_runner_count": "1",
        "runner_fleet_instance_type": "m7g.2xlarge",
        "runner_fleet_architecture": "arm64",
        "runner_fleet_root_volume_gb": "200",
        "runner_fleet_idle_shutdown_minutes": "30",
        "runner_fleet_shutdown_mode": "terminate",
    }


__all__ = [
    "_ChunkedStream",
    "_PRIVATE_KEY",
    "_Process",
    "_SECRET_ARN",
    "_TOKEN",
    "_runner_values",
    "_write_snapshot",
]
