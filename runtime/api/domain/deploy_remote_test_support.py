# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import os

import pytest

from yoke_core.domain import deploy_remote

from yoke_core.domain.deploy_environment_settings import DeployEnvironment

from yoke_core.domain.deploy_remote import (
    AWS_AMBIENT_AUTH_ENV_VARS,
    CommandResult,
    aws_capability_region,
    aws_capability_env,
    aws_machine_capability_env,
    ssh_argv,
)


def _env() -> DeployEnvironment:
    return DeployEnvironment(
        project="yoke",
        deploy_namespace="yoke",
        env_name="prod",
        site_id="yoke-api",
        api_host="api.example.com",
        origin_host="origin.example.com",
        origin_port=80,
        ssh_user="ubuntu",
        ssh_key_path="/keys/origin-example.pem",
        aws_region="us-east-1",
        aws_account_id="123456789012",
        repository_name="yoke-core",
        api_port=8765,
        health_path="/v1/health",
        stack_name="yoke-prod",
        activation_state="active",
        state_backend="s3://yoke-pulumi-state?region=us-east-1",
        database_name="yoke_prod",
    )


class FakeRunner:
    """Records every command; returns scripted results in order."""

    def __init__(self, results=None):
        self.calls = []
        self._results = list(results or [])

    def run(self, argv, *, input_text=None, env=None, timeout=600):
        self.calls.append(
            {
                "argv": list(argv),
                "input_text": input_text,
                "env": env,
                "timeout": timeout,
            }
        )
        if self._results:
            return self._results.pop(0)
        return CommandResult(returncode=0, stdout="", stderr="")
