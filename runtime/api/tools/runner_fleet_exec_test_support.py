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
    schema: int = 1,
) -> Path:
    capabilities: dict[str, object] = {}
    if region is not None:
        capabilities[aws_capability] = {"region": region}
    if aws_capability != "aws-admin":
        capabilities["github-actions-runner-fleet"] = {
            "aws_capability": aws_capability,
        }
    payload = {
        "config_schema": schema,
        "project_id": 42,
        "project_slug": envelope_project or project,
        "renderer_settings": {
            "project": project,
            "deploy_namespace": project,
            "display_name": project.title(),
            "site_id": f"{project}-site",
            "site_settings": {},
            "environments": [],
            "capabilities": capabilities,
        },
    }
    json_helper.dump_path(path, payload)
    return path


def _runner_values() -> dict[str, str]:
    return {
        "runner_fleet_github_private_key_secret_arn": _SECRET_ARN,
        "runner_fleet_github_app_issuer": "Iv1.runner-fleet",
        "runner_fleet_github_installation_id": "123456",
        "runner_fleet_github_repository_id": "789012",
        "runner_fleet_github_api_url": "https://api.github.com",
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
