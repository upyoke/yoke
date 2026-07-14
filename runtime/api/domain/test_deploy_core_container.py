"""Tests for the core-container-deploy executor (fake-runner command plans)."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import deploy_core_container
from yoke_core.domain import deploy_core_container_image
from yoke_core.domain.deploy_core_container import (
    exec_core_container_deploy,
    render_service_files,
    RuntimeDatabaseBinding,
)
from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import CommandResult
from runtime.api.domain.test_deploy_remote import FakeRunner

_BINDING = RuntimeDatabaseBinding(
    host="db.internal",
    database_name="yoke_prod",
    secret_arn="arn:aws:secretsmanager:us-east-1:123:secret:yoke-db",
    region="us-east-1",
)


def _env(**overrides) -> DeployEnvironment:
    values = dict(
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
    values.update(overrides)
    return DeployEnvironment(**values)


class TestResolveEnvironmentDsn:
    def test_render_uses_parent_computed_output_dir(self, monkeypatch):
        """The render subprocess writes where THIS process will read.

        default_render_output_dir is pid-scoped; without an explicit
        --output-dir the child renders into its own run dir and the
        parent reads a path that never existed (live failure 2026-06-09).
        """
        from yoke_core.domain.deploy_core_container import (
            resolve_environment_dsn,
        )

        captured = {}

        def fake_outputs(infra_dir, location, env):
            captured["infra_dir"] = infra_dir
            return {"databaseClusterEndpoint": "ep", "databaseSecretArn": "arn"}

        monkeypatch.setattr(deploy_core_container, "load_stack_outputs", fake_outputs)
        monkeypatch.setattr(
            deploy_core_container,
            "load_secret_string",
            lambda arn, region, env: '{"username": "u", "password": "p", "port": 5432}',
        )
        runner = FakeRunner([CommandResult(0, "", "")])
        dsn, outputs = resolve_environment_dsn(runner, _env(), {}, emit=lambda _l: None)
        argv = runner.calls[0]["argv"]
        assert "--output-dir" in argv
        assert argv[argv.index("--pulumi-stack") + 1] == "yoke-prod"
        out_dir = Path(argv[argv.index("--output-dir") + 1])
        assert captured["infra_dir"] == out_dir / "infra"
        assert "host=ep" in dsn and "dbname=yoke_prod" in dsn
        assert outputs["databaseClusterEndpoint"] == "ep"


class TestRenderServiceFiles:
    def test_compose_pins_image_loopback_port_and_awslogs(self):
        compose, nginx, env_file = render_service_files(
            _env(), _env().image_ref("abc123def456"), _BINDING
        )
        assert (
            "image: 123456789012.dkr.ecr.us-east-1.amazonaws.com/yoke-core:abc123def456"
            in compose
        )
        assert '"127.0.0.1:8765:8765"' in compose
        assert "driver: awslogs" in compose
        assert 'awslogs-group: "/yoke/prod/core"' in compose
        assert 'awslogs-region: "us-east-1"' in compose
        assert "container_name: yoke-core" in compose

    def test_compose_does_not_mount_static_dsn_file(self):
        compose, _, _ = render_service_files(_env(), "img:tag", _BINDING)
        assert "/run/yoke/dsn" not in compose
        assert "./dsn:" not in compose

    def test_nginx_proxies_origin_port_to_container(self):
        _, nginx, _ = render_service_files(_env(), "img:tag", _BINDING)
        assert "listen 80 default_server;" in nginx
        assert "server_name origin.example.com api.example.com;" in nginx
        assert "client_max_body_size" in nginx
        assert "proxy_pass http://127.0.0.1:8765;" in nginx

    def test_env_file_points_at_managed_secret_never_raw_password(self):
        _, _, env_file = render_service_files(_env(), "img:tag", _BINDING)
        assert "YOKE_DB_SECRET_ARN=arn:aws:secretsmanager" in env_file
        assert "YOKE_DB_SECRET_REGION=us-east-1" in env_file
        assert "YOKE_DB_HOST=db.internal" in env_file
        assert "YOKE_DB_NAME=yoke_prod" in env_file
        assert "YOKE_PG_DSN" not in env_file
        assert "password" not in env_file.lower()
        assert "YOKE_ENVIRONMENT=prod" in env_file
        assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in env_file

    def test_env_file_adds_otel_endpoint_when_configured(self):
        _, _, env_file = render_service_files(
            _env(otel_exporter_endpoint="https://otel.example"),
            "img:tag",
            _BINDING,
        )
        assert "OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.example" in env_file


_PRIOR_IMAGE = "123456789012.dkr.ecr.us-east-1.amazonaws.com/yoke-core:prior123"


class _HappyRemoteRunner(FakeRunner):
    """Scripts the full remote convergence happy path by argv inspection."""

    def run(self, argv, *, input_text=None, env=None, timeout=600):
        super().run(argv, input_text=input_text, env=env, timeout=timeout)
        command = argv[-1] if argv and argv[0] == "ssh" else " ".join(argv)
        if "iam/info" in command:
            return CommandResult(0, '{"InstanceProfileArn": "arn:..."}', "")
        if "docker compose run --rm --no-deps" in command:
            return CommandResult(0, "", "")
        if "{{.Config.Image}}" in command:
            # Pre-swap rollback capture probe: a prior container is running.
            return CommandResult(0, f"{_PRIOR_IMAGE}\n", "")
        if "docker inspect" in command:
            return CommandResult(0, "healthy\n", "")
        if "curl -fsS" in command:
            req_id = command.split("x-request-id: ")[1].split('"')[0]
            return CommandResult(
                0,
                "HTTP/1.1 200 OK\n"
                f"x-request-id: {req_id}\n\n"
                '{"status":"ok","schema_ready":true,'
                '"schema_missing_tables":[],"build":"abc123def456",'
                '"engine_version":"0.1.1+launch.25"}',
                "",
            )
        return CommandResult(0, "", "")


def patch_executor_boundaries(monkeypatch, env):
    """Stub every non-remote executor boundary; returns the deploy-event log.

    Module-level so the rollback integration tests
    (test_deploy_core_container_rollback.py) reuse the same seam without
    duplicating it.
    """
    monkeypatch.setattr(
        deploy_core_container,
        "resolve_deploy_environment",
        lambda project, env_name: env,
    )
    monkeypatch.setattr(
        deploy_core_container.github_app_deploy,
        "aws_capability_env",
        lambda project, region: {"AWS_REGION": region},
    )
    monkeypatch.setattr(
        deploy_core_container,
        "resolve_environment_database_binding",
        lambda runner, env_, aws_env, emit: (_BINDING, {}),
    )
    monkeypatch.setattr(
        deploy_core_container_image,
        "resolve_image_tag",
        lambda runner, repo, tag="", declared_branch="": "abc123def456",
    )
    monkeypatch.setattr(
        deploy_core_container,
        "resolve_image_tag",
        lambda runner, repo, tag="", declared_branch="": "abc123def456",
    )
    monkeypatch.setattr(
        deploy_core_container,
        "ensure_image_in_registry",
        lambda runner, env_, aws_env, *, repo_path, tag, emit: env_.image_ref(tag),
    )
    events = []
    monkeypatch.setattr(
        deploy_core_container,
        "_emit_deploy_event",
        lambda env_, image_ref, request_id: events.append(
            (env_.env_name, image_ref, request_id)
        ),
    )
    return events


class TestExecCoreContainerDeploy:
    def _patch_boundaries(self, monkeypatch, env):
        return patch_executor_boundaries(monkeypatch, env)

    def test_full_remote_plan_and_secret_hygiene(self, monkeypatch):
        env = _env()
        events = self._patch_boundaries(monkeypatch, env)
        runner = _HappyRemoteRunner()
        rc = exec_core_container_deploy(
            "yoke",
            "prod",
            repo_path="/repo",
            runner=runner,
            emit=lambda _line: None,
        )
        assert rc == 0
        assert events and events[0][0] == "prod"

        remote_commands = [c["argv"][-1] for c in runner.calls if c["argv"][0] == "ssh"]
        joined = "\n".join(remote_commands)
        assert "apt-get install" not in joined or "docker.io" in joined
        assert "awscli" not in joined
        assert "command -v aws" in joined
        assert "systemctl enable --now docker nginx" in joined
        assert "usermod -aG docker ubuntu" in joined
        assert "/etc/nginx/sites-available/yoke-core.conf" in joined
        assert "rm -f /etc/nginx/sites-enabled/default" in joined
        assert "docker compose pull" in joined
        assert "docker compose run --rm --no-deps --entrypoint python core" in joined
        assert "resolve_dsn_from_env" in joined
        assert "docker compose up -d --remove-orphans --force-recreate" in joined

        # Secret hygiene: the DB password never appears in argv or stdin. The
        # env file carries the managed secret ARN and endpoint facts only; the
        # runtime resolves the current password from Secrets Manager.
        all_argv = "\n".join(" ".join(c["argv"]) for c in runner.calls)
        all_stdin = "\n".join(str(c.get("input_text") or "") for c in runner.calls)
        assert "topsecret" not in all_argv
        assert "topsecret" not in all_stdin
        env_pushes = [
            c
            for c in runner.calls
            if c["argv"][0] == "ssh"
            and c["argv"][-1].endswith(" /opt/yoke-core/.env 600")
        ]
        assert len(env_pushes) == 1
        assert "YOKE_DB_SECRET_ARN=" in env_pushes[0]["input_text"]
        assert "YOKE_DB_HOST=db.internal" in env_pushes[0]["input_text"]
        dsn_pushes = [
            c
            for c in runner.calls
            if c["argv"][0] == "ssh"
            and c["argv"][-1].endswith(" /opt/yoke-core/dsn 444")
        ]
        assert dsn_pushes == []
        assert "chmod 700 /opt/yoke-core" in joined

    def test_declared_branch_threads_into_tag_resolution(self, monkeypatch):
        # The env's declared branch (environments.settings.git.branch)
        # reaches resolve_image_tag so persistent envs pin to branch HEAD.
        env = _env(git_branch="main")
        self._patch_boundaries(monkeypatch, env)
        seen = {}

        def fake_resolve(runner, repo, tag="", *, declared_branch=""):
            seen["declared_branch"] = declared_branch
            return "abc123def456"

        monkeypatch.setattr(deploy_core_container, "resolve_image_tag", fake_resolve)
        rc = exec_core_container_deploy(
            "yoke",
            "prod",
            repo_path="/repo",
            runner=_HappyRemoteRunner(),
            emit=lambda _line: None,
        )
        assert rc == 0
        assert seen["declared_branch"] == "main"

    def test_render_only_environment_refused(self, monkeypatch):
        env = _env(activation_state="render_only")
        self._patch_boundaries(monkeypatch, env)
        rc = exec_core_container_deploy(
            "yoke",
            "stage",
            repo_path="/repo",
            runner=FakeRunner(),
            emit=lambda _line: None,
        )
        assert rc == 1

    def test_prune_runs_after_successful_swap(self, monkeypatch):
        # A health-verified deploy reclaims disk from superseded images so the
        # origin box's small root volume never fills across repeated auto-
        # deploys. The prune runs AFTER the compose swap (post-success), so the
        # prior image survives the mid-deploy rollback window.
        env = _env()
        self._patch_boundaries(monkeypatch, env)
        runner = _HappyRemoteRunner()
        rc = exec_core_container_deploy(
            "yoke",
            "prod",
            repo_path="/repo",
            runner=runner,
            emit=lambda _line: None,
        )
        assert rc == 0
        remote = [c["argv"][-1] for c in runner.calls if c["argv"][0] == "ssh"]
        prune_idx = next(
            i for i, c in enumerate(remote) if c.startswith("python3 - --repository")
        )
        up_idx = next(i for i, c in enumerate(remote) if "docker compose up -d" in c)
        assert prune_idx > up_idx
        assert f"--keep {env.image_ref('abc123def456')}" in remote[prune_idx]
        assert not any("docker image prune --all" in command for command in remote)

    # Health-gate failure + rollback integration tests live in
    # test_deploy_core_container_rollback.py (TestExecutorRollbackIntegration),
    # which imports patch_executor_boundaries and _HappyRemoteRunner from here.
