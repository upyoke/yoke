# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

import shutil

import tempfile

from yoke_core.domain import deploy_core_container

from yoke_core.domain import deploy_core_container_image

from yoke_core.domain.deploy_core_container import (
    exec_core_container_deploy,
    RuntimeDatabaseBinding,
)

from yoke_core.domain.deploy_environment_settings import DeployEnvironment

from yoke_core.domain.deploy_remote import CommandResult

from runtime.api.domain.deploy_remote_test_support import FakeRunner

from runtime.api.tools.pulumi_exec_support_test_support import (
    _install_pulumi_project_files,
)

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
    """Stub every non-remote step runner boundary; returns the deploy-event log.

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
        lambda runner, env_, aws_env, *, repo_path, emit: (_BINDING, {}),
    )
    source = Path(tempfile.mkdtemp(prefix="yoke-service-project-"))
    pack_root = Path(__file__).resolve().parents[3] / "packs"
    for slug in ("container-runtime", "host-maintenance"):
        shutil.copytree(
            pack_root / slug / "versions/1.0.0/files",
            source,
            dirs_exist_ok=True,
        )
    monkeypatch.setattr(
        deploy_core_container,
        "_project_source_root",
        lambda project, repo_path="": source,
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
