"""Tests for deploy remote-execution plumbing (runner seam, ssh, aws env)."""

from __future__ import annotations

from runtime.api.domain.deploy_remote_test_support import (
    FakeRunner as FakeRunner,
    _env as _env,
)


import os

import pytest

from yoke_core.domain import deploy_remote
from yoke_core.domain.deploy_remote import (
    AWS_AMBIENT_AUTH_ENV_VARS,
    aws_capability_region,
    aws_capability_env,
    aws_machine_capability_env,
    ssh_argv,
)


@pytest.fixture(autouse=True)
def _isolate_aws_authority_from_ci(monkeypatch):
    """Each case selects Actions authority explicitly when it needs it."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


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
    def test_machine_authority_reads_slugged_files_without_database(self, monkeypatch):
        reads = []

        def fake_machine_secret(project, cap_type, key):
            reads.append((project, cap_type, key))
            return {
                "access_key_id": "AKIAMACHINE",
                "secret_access_key": "machine-secret",
                "session_token": None,
            }[key]

        monkeypatch.setattr(
            deploy_remote.capability_machine_secrets,
            "read_machine_capability_secret",
            fake_machine_secret,
        )
        monkeypatch.setattr(
            deploy_remote,
            "cmd_capability_get_secret",
            lambda *_args: pytest.fail("consulted the selected database"),
        )

        env = aws_machine_capability_env("yoke", "us-east-1")

        assert env["AWS_ACCESS_KEY_ID"] == "AKIAMACHINE"
        assert env["AWS_SECRET_ACCESS_KEY"] == "machine-secret"
        assert {key for _project, _cap_type, key in reads} == {
            "access_key_id",
            "secret_access_key",
            "session_token",
        }

    def test_materializes_capability_secrets_into_env(self, monkeypatch):
        def fake_secret(project, cap_type, key):
            assert project == "yoke"
            assert cap_type == "aws-admin"
            return {
                "access_key_id": "AKIATEST",
                "secret_access_key": "shh",
                "session_token": None,
            }[key]

        monkeypatch.setattr(deploy_remote, "cmd_capability_get_secret", fake_secret)
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
            lambda *a: {
                "access_key_id": "AKIATEST",
                "secret_access_key": "shh",
                "session_token": None,
            }[a[2]],
        )
        env = aws_capability_env("yoke", "us-east-1")
        detached = {"AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"}
        for name in set(AWS_AMBIENT_AUTH_ENV_VARS) - detached:
            assert name not in env
        for name in detached:
            assert env[name] == os.devnull
        assert env["AWS_PAGER"] == ""

    def test_materializes_capability_session_token(self, monkeypatch):
        monkeypatch.setenv("AWS_SESSION_TOKEN", "ambient-token")
        monkeypatch.setattr(
            deploy_remote,
            "cmd_capability_get_secret",
            lambda *a: {
                "access_key_id": "AKIATEST",
                "secret_access_key": "shh",
                "session_token": "capability-token",
            }[a[2]],
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
            deploy_remote,
            "cmd_capability_get_settings",
            fake_settings,
        )
        monkeypatch.setattr(
            deploy_remote,
            "cmd_capability_get_secret",
            fake_secret,
        )

        region = aws_capability_region(
            "externalwebapp",
            capability_type="runner-aws",
        )
        env = aws_capability_env(
            "externalwebapp",
            region or "",
            capability_type="runner-aws",
        )

        assert region == "eu-west-1"
        assert settings_calls == [("externalwebapp", "runner-aws")]
        assert {call[1] for call in secret_calls} == {"runner-aws"}
        assert env["AWS_ACCESS_KEY_ID"] == "AKIACUSTOM"
        assert env["AWS_SECRET_ACCESS_KEY"] == "custom-secret"
        assert env["AWS_SESSION_TOKEN"] == "custom-session"

    def test_missing_secret_fails_with_seed_recipe(self, monkeypatch):
        monkeypatch.setattr(deploy_remote, "cmd_capability_get_secret", lambda *a: None)
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        with pytest.raises(RuntimeError) as exc:
            aws_capability_env("yoke", "us-east-1")
        assert "aws-admin capability secrets are missing" in str(exc.value)
        assert "capability secret set" in str(exc.value)

    def test_missing_secret_refuses_despite_ambient_aws_login(self, monkeypatch):
        # Outside GitHub Actions the operator's ambient AWS login is never a
        # fallback for missing capability credentials.
        monkeypatch.setattr(deploy_remote, "cmd_capability_get_secret", lambda *a: None)
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ASIA_AMBIENT")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ambient-secret")
        with pytest.raises(RuntimeError, match="never falls back to the ambient"):
            aws_capability_env("yoke", "us-east-1")

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
