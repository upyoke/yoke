"""Tests for the environment-activate executor (fake-runner state machine)."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import deploy_environment_activate
from yoke_core.domain.deploy_environment_activate import (
    EnvironmentActivateError,
    ensure_instance_running,
    exec_environment_activate,
    wait_ssh_reachable,
)
from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import CommandResult
from runtime.api.domain.test_deploy_remote import FakeRunner


def _env(**overrides) -> DeployEnvironment:
    values = dict(
        project="yoke",
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
    values.update(overrides)
    return DeployEnvironment(**values)


def _describe(rows) -> CommandResult:
    return CommandResult(0, json.dumps(rows), "")


class TestEnsureInstanceRunning:
    def test_running_instance_is_left_alone(self):
        runner = FakeRunner([_describe([["i-0abc", "running"]])])
        instance = ensure_instance_running(
            runner, _env(), {"AWS_REGION": "us-east-1"}, lambda _l: None
        )
        assert instance == "i-0abc"
        assert len(runner.calls) == 1
        assert "tag:Name,Values=yoke-prod/VpsInstance" in " ".join(
            runner.calls[0]["argv"]
        )

    def test_stopped_instance_is_started_and_waited(self):
        runner = FakeRunner(
            [
                _describe([["i-0abc", "stopped"]]),
                CommandResult(0, "", ""),  # start-instances
                CommandResult(0, "", ""),  # wait instance-running
            ]
        )
        instance = ensure_instance_running(
            runner, _env(), {}, lambda _l: None
        )
        assert instance == "i-0abc"
        argvs = [c["argv"] for c in runner.calls]
        assert argvs[1][:3] == ["aws", "ec2", "start-instances"]
        assert argvs[2][:4] == ["aws", "ec2", "wait", "instance-running"]

    def test_missing_instance_names_stack_remediation(self):
        runner = FakeRunner([_describe([])])
        with pytest.raises(EnvironmentActivateError) as exc:
            ensure_instance_running(runner, _env(), {}, lambda _l: None)
        assert "yoke-prod" in str(exc.value)

    def test_duplicate_instances_refused(self):
        runner = FakeRunner(
            [_describe([["i-0abc", "running"], ["i-0def", "stopped"]])]
        )
        with pytest.raises(EnvironmentActivateError) as exc:
            ensure_instance_running(runner, _env(), {}, lambda _l: None)
        assert "multiple instances" in str(exc.value)


class TestWaitSshReachable:
    def test_succeeds_after_retries(self):
        runner = FakeRunner(
            [
                CommandResult(255, "", "Connection refused"),
                CommandResult(0, "ssh-ok\n", ""),
            ]
        )
        wait_ssh_reachable(
            runner, _env(), lambda _l: None, sleeper=lambda _s: None
        )
        assert len(runner.calls) == 2

    def test_times_out_with_last_error(self, monkeypatch):
        clock = iter([0.0, 1.0, 200.0, 300.0])
        monkeypatch.setattr(
            deploy_environment_activate.time, "monotonic", lambda: next(clock)
        )
        runner = FakeRunner([CommandResult(255, "", "Connection refused")])
        with pytest.raises(EnvironmentActivateError) as exc:
            wait_ssh_reachable(
                runner, _env(), lambda _l: None,
                timeout_s=100, sleeper=lambda _s: None,
            )
        assert "Connection refused" in str(exc.value)


class TestExecEnvironmentActivate:
    def test_happy_path(self, monkeypatch):
        monkeypatch.setattr(
            deploy_environment_activate,
            "resolve_deploy_environment",
            lambda project, env_name: _env(),
        )
        monkeypatch.setattr(
            deploy_environment_activate,
            "aws_capability_env",
            lambda project, region: {},
        )
        runner = FakeRunner(
            [
                _describe([["i-0abc", "running"]]),
                CommandResult(0, "ssh-ok\n", ""),
            ]
        )
        assert (
            exec_environment_activate(
                "yoke", "prod", runner=runner, emit=lambda _l: None
            )
            == 0
        )

    def test_render_only_refused(self, monkeypatch):
        monkeypatch.setattr(
            deploy_environment_activate,
            "resolve_deploy_environment",
            lambda project, env_name: _env(activation_state="render_only"),
        )
        assert (
            exec_environment_activate(
                "yoke", "stage", runner=FakeRunner(), emit=lambda _l: None
            )
            == 1
        )
