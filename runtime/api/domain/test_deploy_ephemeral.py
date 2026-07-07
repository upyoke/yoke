"""Tests for the ephemeral-deploy executor (fake-runner command plans)."""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.domain import deploy_ephemeral
from yoke_core.domain import deploy_ephemeral_remote as remote
from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import CommandResult
from yoke_core.domain.ephemeral_substrate import EphemeralPolicy
from runtime.api.domain.test_deploy_remote import FakeRunner


def _policy(**overrides):
    values = dict(
        project="yoke",
        trigger="flow",
        preview_domain="preview.example.com",
        host_env="stage",
        api_base_port=9000,
        web_base_port=4000,
        port_range=100,
        ttl_hours=24,
    )
    values.update(overrides)
    return EphemeralPolicy(**values)


def _env(**overrides) -> DeployEnvironment:
    values = dict(
        project="yoke",
        env_name="stage",
        site_id="yoke-api",
        api_host="api.stage.example.com",
        origin_host="origin.stage.example.com",
        origin_port=80,
        ssh_user="ubuntu",
        ssh_key_path="/keys/origin-example.pem",
        aws_region="us-east-1",
        aws_account_id="123456789012",
        repository_name="yoke-core",
        api_port=8765,
        health_path="/v1/health",
        stack_name="yoke-stage",
        activation_state="active",
        state_backend="s3://yoke-pulumi-state?region=us-east-1",
        database_name="yoke_stage",
    )
    values.update(overrides)
    return DeployEnvironment(**values)


_SHA = "1234567890abcdef1234567890abcdef12345678"
_SLUG = "ephemeral-substrate-preview"
_PORT = 9067  # derive_port golden vector for the slug above


class _Tracker:
    def __init__(self):
        self.calls = []

    def __call__(self, project, branch, updates, item_label=""):
        self.calls.append((project, branch, dict(updates), item_label))


@pytest.fixture
def deploy_seams(monkeypatch):
    """Mock every non-runner seam so command plans drive the assertions."""
    tracker = _Tracker()
    monkeypatch.setattr(
        deploy_ephemeral, "load_ephemeral_policy", lambda p: _policy()
    )
    monkeypatch.setattr(
        deploy_ephemeral, "resolve_deploy_environment",
        lambda p, e: _env(),
    )
    monkeypatch.setattr(
        deploy_ephemeral, "aws_capability_env", lambda p, r: {"AWS": "1"}
    )
    monkeypatch.setattr(
        deploy_ephemeral, "ensure_instance_running",
        lambda runner, env, aws_env, emit: None,
    )
    monkeypatch.setattr(
        deploy_ephemeral, "wait_ssh_reachable",
        lambda runner, env, emit: None,
    )
    monkeypatch.setattr(
        deploy_ephemeral, "ensure_image_in_registry",
        lambda runner, env, aws_env, repo_path, tag, emit: (
            f"reg/yoke-core:{tag}"
        ),
    )
    monkeypatch.setattr(
        deploy_ephemeral, "wait_container_healthy",
        lambda runner, env, name, emit: None,
    )
    monkeypatch.setattr(
        deploy_ephemeral, "render_webapp_template",
        lambda relative, values: f"rendered:{relative}",
    )
    monkeypatch.setattr(deploy_ephemeral, "track", tracker)
    monkeypatch.setattr(
        deploy_ephemeral, "emit_ephemeral_event", lambda *a, **k: None
    )
    return tracker


def _scripted_runner():
    """Results in executor call order (branch sha + remote convergence)."""
    return FakeRunner([
        CommandResult(0, _SHA + "\n", ""),       # git rev-parse branch
        CommandResult(0, "", ""),                # tls cert probe (present)
        CommandResult(0, "", ""),                # njs package probe (present)
        CommandResult(0, "", ""),                # njs dir mkdir
        CommandResult(0, "", ""),                # njs script push
        CommandResult(0, "", ""),                # nginx site push
        CommandResult(0, "", ""),                # nginx activate
        CommandResult(0, "", ""),                # cleanup script push
        CommandResult(0, "", ""),                # cleanup cron push
        CommandResult(0, "cafe01\n", ""),        # existing db-password read
        CommandResult(0, "", ""),                # slug dir prepare
        CommandResult(0, "", ""),                # compose push
        CommandResult(0, "", ""),                # db-password push
        CommandResult(0, "", ""),                # .env push
        CommandResult(0, "", ""),                # dsn push
        CommandResult(0, "", ""),                # compose pull
        CommandResult(0, "bootstrap complete", ""),  # in-container bootstrap
        CommandResult(0, "", ""),                # compose up
        CommandResult(0, "x-request-id: RID", ""),   # slug health (patched id)
    ])


class TestExecEphemeralDeploy:
    def test_full_deploy_command_plan(self, deploy_seams, monkeypatch):
        runner = _scripted_runner()
        monkeypatch.setattr(
            deploy_ephemeral, "uuid", mock.Mock(uuid4=lambda: "RID")
        )
        health_calls = []
        monkeypatch.setattr(
            "yoke_core.tools.executors.exec_health_check",
            lambda url, request_id="": health_calls.append(url) or 0,
        )
        rc = deploy_ephemeral.exec_ephemeral_deploy(
            "yoke", branch=_SLUG, repo_path="/repo",
            item_label="YOK-9", runner=runner, emit=lambda _l: None,
        )
        assert rc == 0
        joined = [
            c["argv"][-1] if c["argv"][0] == "ssh" else " ".join(c["argv"])
            for c in runner.calls
        ]
        assert joined[0] == f"git -C /repo rev-parse {_SLUG}"
        bootstrap = next(c for c in joined if "environment_bootstrap" in c)
        assert "YOKE_DB_INIT_ALLOW=1" in bootstrap
        assert "docker compose run --rm" in bootstrap
        up = next(c for c in joined if "compose up" in c)
        assert "--force-recreate" in up and "--remove-orphans" in up
        health = next(c for c in joined if "curl" in c)
        assert f"127.0.0.1:{_PORT}/v1/health" in health
        # Public wildcard health check ran against the preview URL.
        assert health_calls == [
            f"https://{_SLUG}.preview.example.com/v1/health"
        ]
        # Tracking: created with ports/url/sha, then flipped to running.
        first, last = deploy_seams.calls[0], deploy_seams.calls[-1]
        assert first[2]["port_api"] == str(_PORT)
        assert first[2]["deployed_sha"] == _SHA
        assert first[3] == "YOK-9"
        assert last[2]["status"] == "running"

    def test_existing_db_password_is_reused(self, deploy_seams, monkeypatch):
        runner = _scripted_runner()
        monkeypatch.setattr(
            deploy_ephemeral, "uuid", mock.Mock(uuid4=lambda: "RID")
        )
        monkeypatch.setattr(
            "yoke_core.tools.executors.exec_health_check",
            lambda url, request_id="": 0,
        )
        deploy_ephemeral.exec_ephemeral_deploy(
            "yoke", branch=_SLUG, repo_path="/repo",
            runner=runner, emit=lambda _l: None,
        )
        pushes = [
            c for c in runner.calls
            if c["argv"][0] == "ssh" and c["input_text"]
        ]
        password_push = next(
            c for c in pushes if "db-password" in c["argv"][-1]
        )
        assert password_push["input_text"] == "cafe01\n"
        dsn_push = next(c for c in pushes if "/dsn" in c["argv"][-1])
        assert "password=cafe01" in dsn_push["input_text"]

    def test_branch_required(self, deploy_seams):
        rc = deploy_ephemeral.exec_ephemeral_deploy(
            "yoke", branch="", runner=FakeRunner(), emit=lambda _l: None,
        )
        assert rc == 1

    def test_render_only_host_env_refused(self, deploy_seams, monkeypatch):
        monkeypatch.setattr(
            deploy_ephemeral, "resolve_deploy_environment",
            lambda p, e: _env(activation_state="render_only"),
        )
        rc = deploy_ephemeral.exec_ephemeral_deploy(
            "yoke", branch=_SLUG, repo_path="/repo",
            runner=FakeRunner(), emit=lambda _l: None,
        )
        assert rc == 1

    def test_failure_marks_row_failed(self, deploy_seams, monkeypatch):
        runner = FakeRunner([
            CommandResult(0, _SHA + "\n", ""),
            CommandResult(1, "", "ssh exploded"),  # tls probe
            CommandResult(1, "", "no certbot"),    # certbot pkg probe
            CommandResult(1, "", "apt broken"),    # certbot install -> fail
        ])
        rc = deploy_ephemeral.exec_ephemeral_deploy(
            "yoke", branch=_SLUG, repo_path="/repo",
            runner=runner, emit=lambda _l: None,
        )
        assert rc == 1
        assert deploy_seams.calls[-1][2] == {"status": "failed"}


class TestExecEphemeralTeardown:
    def test_teardown_command_plan(self, deploy_seams):
        runner = FakeRunner([
            CommandResult(0, "", ""),  # compose down
            CommandResult(0, "", ""),  # rm -rf dir
        ])
        rc = deploy_ephemeral.exec_ephemeral_teardown(
            "yoke", branch=_SLUG, runner=runner, emit=lambda _l: None,
        )
        assert rc == 0
        down = runner.calls[0]["argv"][-1]
        assert "docker compose down --volumes --remove-orphans" in down
        assert runner.calls[1]["argv"][-1] == (
            f"rm -rf ~/yoke-ephemeral/{_SLUG}"
        )
        assert deploy_seams.calls[-1][2] == {"status": "stopped"}


class TestRemoteHelpers:
    def test_certbot_issued_only_when_cert_absent(self):
        runner = FakeRunner([
            CommandResult(1, "", ""),  # cert probe -> absent
            CommandResult(0, "", ""),  # certbot packages present
            CommandResult(0, "", ""),  # certonly
        ])
        remote.ensure_wildcard_tls(
            runner, _env(), "preview.example.com", lambda _l: None
        )
        issue = runner.calls[-1]["argv"][-1]
        assert 'certbot certonly --dns-route53 -d "*.preview.example.com"' in issue
        assert "--register-unsafely-without-email" in issue

    def test_dsn_pushed_world_readable_in_private_dir(self):
        runner = FakeRunner()
        remote.converge_slug_project(
            runner, _env(), "~/yoke-ephemeral/x", "compose", "envfile",
            "dsn-line", "cafe01", lambda _l: None,
        )
        prepare = runner.calls[0]["argv"][-1]
        assert "chmod 700 ~/yoke-ephemeral/x" in prepare
        dsn = next(
            c for c in runner.calls if "/dsn" in c["argv"][-1]
        )["argv"][-1]
        assert "install -m 444" in dsn

    def test_password_hex_guard_rejects_garbage(self):
        runner = FakeRunner([CommandResult(0, "not hex!\n", "")])
        value = remote.read_existing_db_password(
            runner, _env(), "~/yoke-ephemeral/x"
        )
        assert value == ""
