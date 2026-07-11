"""Tests for deploy remote-execution plumbing (runner seam, ssh, aws env)."""

from __future__ import annotations

import pytest

from yoke_core.domain import deploy_remote
from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import (
    AWS_AMBIENT_AUTH_ENV_VARS,
    CommandResult,
    aws_capability_region,
    aws_capability_env,
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


class TestSshArgv:
    def test_builds_batchmode_keyed_invocation(self):
        argv = ssh_argv(_env(), "echo hi")
        assert argv[0] == "ssh"
        assert argv[1:3] == ["-i", "/keys/origin-example.pem"]
        assert "BatchMode=yes" in argv
        assert "StrictHostKeyChecking=accept-new" in argv
        assert argv[-2] == "ubuntu@origin.example.com"
        assert argv[-1] == "echo hi"

    def test_connect_timeout_override(self):
        argv = ssh_argv(_env(), "true", connect_timeout=30)
        assert "ConnectTimeout=30" in argv
        assert "ConnectTimeout=10" not in argv


class TestAwsCapabilityEnv:
    def test_materializes_capability_secrets_into_env(self, monkeypatch):
        def fake_secret(project, cap_type, key):
            assert project == "yoke"
            assert cap_type == "aws-admin"
            return {
                "access_key_id": "AKIATEST",
                "secret_access_key": "shh",
                "session_token": None,
            }[key]

        monkeypatch.setattr(
            deploy_remote, "cmd_capability_get_secret", fake_secret
        )
        env = aws_capability_env("yoke", "us-east-1")
        assert env["AWS_ACCESS_KEY_ID"] == "AKIATEST"
        assert env["AWS_SECRET_ACCESS_KEY"] == "shh"
        assert env["AWS_DEFAULT_REGION"] == "us-east-1"
        assert env["AWS_REGION"] == "us-east-1"
        assert env["AWS_PAGER"] == ""

    def test_strips_ambient_aws_auth_overrides(self, monkeypatch):
        for name in AWS_AMBIENT_AUTH_ENV_VARS:
            monkeypatch.setenv(name, f"ambient-{name}")
        monkeypatch.setattr(
            deploy_remote,
            "cmd_capability_get_secret",
            lambda *a: {"access_key_id": "AKIATEST",
                        "secret_access_key": "shh",
                        "session_token": None}[a[2]],
        )
        env = aws_capability_env("yoke", "us-east-1")
        for name in AWS_AMBIENT_AUTH_ENV_VARS:
            assert name not in env
        assert env["AWS_PAGER"] == ""

    def test_materializes_capability_session_token(self, monkeypatch):
        monkeypatch.setenv("AWS_SESSION_TOKEN", "ambient-token")
        monkeypatch.setattr(
            deploy_remote,
            "cmd_capability_get_secret",
            lambda *a: {"access_key_id": "AKIATEST",
                        "secret_access_key": "shh",
                        "session_token": "capability-token"}[a[2]],
        )
        env = aws_capability_env("yoke", "us-east-1")
        assert env["AWS_SESSION_TOKEN"] == "capability-token"

    def test_reads_region_from_capability_settings(self, monkeypatch):
        monkeypatch.setattr(
            deploy_remote,
            "cmd_capability_get_settings",
            lambda project, cap_type: '{"region":"us-west-2"}',
        )
        assert aws_capability_region("yoke") == "us-west-2"

    def test_custom_capability_selects_settings_and_secrets(self, monkeypatch):
        settings_calls = []
        secret_calls = []

        def fake_settings(project, cap_type):
            settings_calls.append((project, cap_type))
            return '{"region":"eu-west-1"}'

        def fake_secret(project, cap_type, key):
            secret_calls.append((project, cap_type, key))
            return {
                "access_key_id": "AKIACUSTOM",
                "secret_access_key": "custom-secret",
                "session_token": "custom-session",
            }[key]

        monkeypatch.setattr(
            deploy_remote, "cmd_capability_get_settings", fake_settings,
        )
        monkeypatch.setattr(
            deploy_remote, "cmd_capability_get_secret", fake_secret,
        )

        region = aws_capability_region(
            "buzz", capability_type="runner-aws",
        )
        env = aws_capability_env(
            "buzz", region or "", capability_type="runner-aws",
        )

        assert region == "eu-west-1"
        assert settings_calls == [("buzz", "runner-aws")]
        assert {call[1] for call in secret_calls} == {"runner-aws"}
        assert env["AWS_ACCESS_KEY_ID"] == "AKIACUSTOM"
        assert env["AWS_SECRET_ACCESS_KEY"] == "custom-secret"
        assert env["AWS_SESSION_TOKEN"] == "custom-session"

    def test_missing_secret_fails_with_seed_recipe(self, monkeypatch):
        monkeypatch.setattr(
            deploy_remote, "cmd_capability_get_secret", lambda *a: None
        )
        # No capability creds AND no ambient creds -> loud failure (a naked
        # unauthenticated aws call is never the fallback).
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        with pytest.raises(RuntimeError) as exc:
            aws_capability_env("yoke", "us-east-1")
        assert "aws-admin capability secrets are missing" in str(exc.value)
        assert "capability secret set" in str(exc.value)

    def test_missing_secret_falls_back_to_ambient_oidc_creds(self, monkeypatch):
        # An ephemeral CI runner has no capability store, but the GitHub-OIDC
        # role exports a real authenticated AWS credential set; use it, keep it
        # intact, and only pin the region.
        monkeypatch.setattr(
            deploy_remote, "cmd_capability_get_secret", lambda *a: None
        )
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ASIA_OIDC")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "oidc-secret")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "oidc-session-token")
        env = aws_capability_env("yoke", "us-east-1")
        assert env["AWS_ACCESS_KEY_ID"] == "ASIA_OIDC"
        assert env["AWS_SECRET_ACCESS_KEY"] == "oidc-secret"
        assert env["AWS_SESSION_TOKEN"] == "oidc-session-token"
        assert env["AWS_DEFAULT_REGION"] == "us-east-1"
        assert env["AWS_REGION"] == "us-east-1"

    def test_actions_oidc_precedes_unreachable_capability_store(self, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ASIA_ACTIONS")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "actions-secret")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "actions-session")
        monkeypatch.setattr(
            deploy_remote,
            "cmd_capability_get_secret",
            lambda *args: pytest.fail("consulted capability store in Actions"),
        )

        env = aws_capability_env("yoke", "us-east-1")

        assert env["AWS_ACCESS_KEY_ID"] == "ASIA_ACTIONS"
        assert env["AWS_SESSION_TOKEN"] == "actions-session"

    def test_actions_without_oidc_credentials_fails_before_lookup(self, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.setattr(
            deploy_remote,
            "cmd_capability_get_secret",
            lambda *args: pytest.fail("consulted capability store in Actions"),
        )

        with pytest.raises(RuntimeError, match="configure-aws-credentials"):
            aws_capability_env("yoke", "us-east-1")
