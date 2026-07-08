"""Tests for the environment-bootstrap deploy executor."""

from __future__ import annotations

import sys

from yoke_core.domain import deploy_environment_bootstrap
from yoke_core.domain.deploy_environment_bootstrap import (
    _dsn_port,
    _localize_dsn,
    exec_environment_bootstrap,
)
from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import CommandResult
from runtime.api.domain.test_deploy_remote import FakeRunner

_DSN = (
    "host=stage-db.cluster-abc.us-east-1.rds.amazonaws.com port=5432 "
    "user=yoke_admin password=hunter2 dbname=yoke_stage"
)
_ENDPOINT = "stage-db.cluster-abc.us-east-1.rds.amazonaws.com"


def _env(**overrides) -> DeployEnvironment:
    values = dict(
        project="yoke",
        deploy_namespace="yoke",
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


def _patch_resolution(monkeypatch, env=None, outputs=None):
    monkeypatch.setattr(
        deploy_environment_bootstrap,
        "resolve_deploy_environment",
        lambda project, env_name: env or _env(),
    )
    monkeypatch.setattr(
        deploy_environment_bootstrap,
        "aws_capability_env",
        lambda project, region: {"AWS_DEFAULT_REGION": region},
    )
    monkeypatch.setattr(
        deploy_environment_bootstrap,
        "resolve_environment_dsn",
        lambda runner, env_, aws_env, emit: (
            _DSN,
            outputs if outputs is not None
            else {"databaseClusterEndpoint": _ENDPOINT},
        ),
    )
    activations = []
    monkeypatch.setattr(
        deploy_environment_bootstrap,
        "ensure_instance_running",
        lambda runner, env_, aws_env, emit: activations.append("run")
        or "i-0abc",
    )
    monkeypatch.setattr(
        deploy_environment_bootstrap,
        "wait_ssh_reachable",
        lambda runner, env_, emit: activations.append("ssh"),
    )
    monkeypatch.setattr(
        deploy_environment_bootstrap, "free_local_port", lambda: 54441
    )
    return activations


class TestDsnHelpers:
    def test_dsn_port_parsed(self):
        assert _dsn_port(_DSN) == 5432
        assert _dsn_port("host=x user=y dbname=z") == 5432

    def test_localize_rewrites_host_and_port_once(self):
        local = _localize_dsn(_DSN, 54441)
        assert "host=127.0.0.1" in local
        assert "port=54441" in local
        assert _ENDPOINT not in local
        assert "password=hunter2" in local
        assert "dbname=yoke_stage" in local


class TestExecEnvironmentBootstrap:
    def test_render_only_refused_with_remediation(self, monkeypatch, capsys):
        monkeypatch.setattr(
            deploy_environment_bootstrap,
            "resolve_deploy_environment",
            lambda project, env_name: _env(activation_state="render_only"),
        )
        rc = exec_environment_bootstrap(
            "yoke", "stage", runner=FakeRunner(), emit=lambda _l: None
        )
        assert rc == 1
        err = capsys.readouterr().err
        assert "render_only" in err
        assert "yoke-stage" in err
        assert "environment-merge-settings" in err

    def test_happy_path_tunnels_and_pins_dsn(self, monkeypatch):
        activations = _patch_resolution(monkeypatch)
        monkeypatch.setenv("YOKE_PG_DSN_FILE", "/should/be/dropped")
        monkeypatch.setenv("YOKE_DB_INIT_DONE", "1")
        events = []
        monkeypatch.setattr(
            deploy_environment_bootstrap,
            "_emit_bootstrap_event",
            lambda env: events.append(env.env_name),
        )
        runner = FakeRunner(
            [
                CommandResult(0, "", ""),  # tunnel open
                CommandResult(0, "[env-bootstrap] bootstrap complete\n", ""),
                CommandResult(0, "", ""),  # tunnel close (pkill)
            ]
        )
        rc = exec_environment_bootstrap(
            "yoke", "stage", runner=runner, emit=lambda _l: None
        )
        assert rc == 0
        assert events == ["stage"]
        assert activations == ["run", "ssh"]
        assert len(runner.calls) == 3

        tunnel = runner.calls[0]["argv"]
        forward = f"127.0.0.1:54441:{_ENDPOINT}:5432"
        assert tunnel[0] == "ssh"
        assert "-L" in tunnel and forward in tunnel
        assert "ubuntu@origin.stage.example.com" in tunnel

        bootstrap = runner.calls[1]
        assert bootstrap["argv"] == [
            sys.executable, "-m", "yoke_core.domain.environment_bootstrap",
        ]
        assert bootstrap["env"]["YOKE_PG_DSN"] == _localize_dsn(_DSN, 54441)
        assert bootstrap["env"]["YOKE_DB_INIT_ALLOW"] == "1"
        assert "YOKE_PG_DSN_FILE" not in bootstrap["env"]
        assert "YOKE_DB_INIT_DONE" not in bootstrap["env"]

        assert runner.calls[2]["argv"][0] == "pkill"
        assert forward in " ".join(runner.calls[2]["argv"])

    def test_missing_endpoint_output_fails(self, monkeypatch, capsys):
        _patch_resolution(monkeypatch, outputs={})
        rc = exec_environment_bootstrap(
            "yoke", "stage", runner=FakeRunner(), emit=lambda _l: None
        )
        assert rc == 1
        assert "databaseClusterEndpoint" in capsys.readouterr().err

    def test_tunnel_open_failure_fails_loudly(self, monkeypatch, capsys):
        _patch_resolution(monkeypatch)
        runner = FakeRunner([CommandResult(255, "", "bind failed")])
        rc = exec_environment_bootstrap(
            "yoke", "stage", runner=runner, emit=lambda _l: None
        )
        assert rc == 1
        assert "bind failed" in capsys.readouterr().err
        assert len(runner.calls) == 1  # no bootstrap subprocess attempted

    def test_subprocess_failure_still_closes_tunnel(self, monkeypatch, capsys):
        _patch_resolution(monkeypatch)
        events = []
        monkeypatch.setattr(
            deploy_environment_bootstrap,
            "_emit_bootstrap_event",
            lambda env: events.append(env.env_name),
        )
        runner = FakeRunner(
            [
                CommandResult(0, "", ""),  # tunnel open
                CommandResult(1, "", "init module flow exited 3"),
                CommandResult(0, "", ""),  # tunnel close
            ]
        )
        rc = exec_environment_bootstrap(
            "yoke", "stage", runner=runner, emit=lambda _l: None
        )
        assert rc == 1
        assert events == []
        assert runner.calls[2]["argv"][0] == "pkill"
        assert "init module flow" in capsys.readouterr().err

    def test_dsn_never_emitted(self, monkeypatch, capsys):
        _patch_resolution(monkeypatch)
        monkeypatch.setattr(
            deploy_environment_bootstrap,
            "_emit_bootstrap_event",
            lambda env: None,
        )
        lines = []
        runner = FakeRunner(
            [
                CommandResult(0, "", ""),
                CommandResult(0, "done\n", ""),
                CommandResult(0, "", ""),
            ]
        )
        rc = exec_environment_bootstrap(
            "yoke", "stage", runner=runner, emit=lines.append
        )
        assert rc == 0
        captured = capsys.readouterr()
        blob = "\n".join(lines) + captured.out + captured.err
        assert "hunter2" not in blob
        assert _DSN not in blob


class TestMain:
    def test_usage_on_bad_args(self, capsys):
        assert deploy_environment_bootstrap.main([]) == 2
        assert deploy_environment_bootstrap.main(["yoke"]) == 2
        assert "Usage" in capsys.readouterr().err

    def test_dispatches_project_env(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            deploy_environment_bootstrap,
            "exec_environment_bootstrap",
            lambda project, env_name: seen.append((project, env_name)) or 0,
        )
        assert deploy_environment_bootstrap.main(["yoke", "stage"]) == 0
        assert seen == [("yoke", "stage")]
