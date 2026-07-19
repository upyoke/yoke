"""Deploy a DB-declared Yoke core-service environment.

The executor resolves infrastructure and image authority, converges the origin
host, swaps the container, gates on container and nginx health, and performs a
bounded rollback after a failed health gate. Secrets travel only through
subprocess environments or SSH stdin; emitted progress is redaction-safe.
"""

from __future__ import annotations

import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from yoke_core.domain.cloud_db_secret_dsn import (
    DB_SECRET_ARN_ENV,
    DB_SECRET_HOST_ENV,
    DB_SECRET_NAME_ENV,
    DB_SECRET_PORT_ENV,
    DB_SECRET_REGION_ENV,
)
from yoke_core.domain.deploy_core_container_events import (
    emit_deploy_event as _emit_deploy_event,
)
from yoke_core.domain.deploy_core_container_image import (
    CoreDeployError,
    ensure_image_in_registry,
    resolve_image_tag,
)
from yoke_core.domain.deploy_core_container_remote import (
    RemoteConvergenceError,
    compose_pull,
    compose_up,
    ensure_compose_project,
    ensure_ecr_credential_helper,
    ensure_instance_profile,
    ensure_nginx_site,
    ensure_runtime_packages,
    prune_superseded_images,
    verify_runtime_database_secret_access,
    verify_origin_health,
    wait_container_healthy,
)
from yoke_core.domain.deploy_core_container_rollback import (
    attempt_rollback,
    capture_running_image_ref,
)
from yoke_core.domain.deploy_environment_settings import (
    DeployEnvironment,
    DeployEnvironmentError,
    resolve_deploy_environment,
)
from yoke_core.domain.deploy_remote import CommandRunner
from yoke_core.domain import deploy_core_github_app as github_app_deploy
from yoke_core.domain.deploy_core_container_source import (
    project_source_root as _project_source_root,
)
from yoke_core.domain.pack_render import render_pack_text
from yoke_core.domain.project_renderer_pulumi import (
    gather_pulumi_values,
    render_pulumi_artifacts,
)
from yoke_core.domain.project_renderer_settings import load_project_renderer_settings
from yoke_core.domain.yoke_cloud_db_authority import (
    DEFAULT_POSTGRES_PORT,
    PostgresAuthorityLocation,
    PostgresSecret,
    build_libpq_dsn,
    endpoint_and_secret_arn,
    load_secret_string,
    load_stack_outputs,
)


def _emit(line: str) -> None:
    print(line, flush=True)


def _render_service_template(project_root: Path, name: str, values: dict) -> str:
    template = project_root / "ops" / "core-service" / name
    if not template.is_file():
        raise CoreDeployError(f"[core-deploy] project-owned Pack file missing: {template}")
    return render_pack_text(template.read_text(), values)


@dataclass(frozen=True)
class RuntimeDatabaseBinding:
    """Non-secret cloud database binding for the core-service container."""

    host: str
    database_name: str
    secret_arn: str
    region: str
    port: int = DEFAULT_POSTGRES_PORT


def _load_environment_stack_binding(
    runner: CommandRunner,
    env: DeployEnvironment,
    aws_env: dict,
    *,
    repo_path: str | Path = "",
    emit: Callable[[str], None] = _emit,
) -> tuple[RuntimeDatabaseBinding, dict]:
    """Resolve the env's endpoint + secret ARN from stack outputs."""
    source_root = _project_source_root(env.project, repo_path)
    settings = load_project_renderer_settings(env.project)
    values = gather_pulumi_values(
        env.project,
        source_root,
        settings,
        pulumi_stack=env.stack_name,
    )
    with tempfile.TemporaryDirectory(prefix="yoke-core-pulumi-") as raw_temp:
        out_dir = Path(raw_temp)
        render_pulumi_artifacts(
            env.project,
            values,
            source_root,
            out_dir,
            True,
            settings,
            pulumi_stack=env.stack_name,
        )
        infra_dir = out_dir / "infra"
        location = PostgresAuthorityLocation(
            stack=env.stack_name,
            database_name=env.database_name,
            state_backend=env.state_backend,
            region=env.aws_region,
        )
        try:
            outputs = load_stack_outputs(infra_dir, location, env=aws_env)
            endpoint, secret_arn = endpoint_and_secret_arn(outputs, location)
        except Exception as exc:
            raise CoreDeployError(
                f"[core-deploy] env database binding failed for stack "
                f"{env.stack_name}: {exc}"
            ) from exc
    emit(f"  [core-deploy] database endpoint resolved: {endpoint}")
    return (
        RuntimeDatabaseBinding(
            host=endpoint,
            database_name=env.database_name,
            secret_arn=secret_arn,
            region=env.aws_region,
        ),
        dict(outputs),
    )


def resolve_environment_database_binding(
    runner: CommandRunner,
    env: DeployEnvironment,
    aws_env: dict,
    *,
    repo_path: str | Path = "",
    emit: Callable[[str], None] = _emit,
) -> tuple[RuntimeDatabaseBinding, dict]:
    """Resolve the non-secret DB binding the container uses at runtime."""
    return _load_environment_stack_binding(
        runner, env, aws_env, repo_path=repo_path, emit=emit
    )


def resolve_environment_dsn(
    runner: CommandRunner,
    env: DeployEnvironment,
    aws_env: dict,
    *,
    repo_path: str | Path = "",
    emit: Callable[[str], None] = _emit,
) -> tuple[str, dict]:
    """Resolve the env's libpq DSN from stack outputs + Secrets Manager.

    Also returns the full (non-secret) stack outputs mapping so callers can
    reuse facts like the instance id without a second Pulumi roundtrip.
    """
    binding, outputs = _load_environment_stack_binding(
        runner, env, aws_env, repo_path=repo_path, emit=emit
    )
    try:
        secret = PostgresSecret.from_json(
            load_secret_string(binding.secret_arn, region=binding.region, env=aws_env)
        )
    except Exception as exc:
        raise CoreDeployError(
            f"[core-deploy] env DSN resolution failed for stack {env.stack_name}: {exc}"
        ) from exc
    dsn = build_libpq_dsn(
        host=binding.host,
        database=binding.database_name,
        secret=secret,
        port=secret.port or binding.port,
    )
    return dsn, outputs


def render_service_files(
    env: DeployEnvironment,
    image_ref: str,
    database: RuntimeDatabaseBinding,
    *,
    repo_path: str | Path,
) -> tuple[str, str, str]:
    """Render (compose_yaml, nginx_site, env_file) for the target env.

    The env file is deliberately password-free: it carries the RDS-managed
    secret ARN plus endpoint facts, and the container resolves the current
    password from Secrets Manager at connection time.
    """
    values = {
        "project": env.project,
        "env_name": env.env_name,
        "container_name": f"{env.deploy_namespace}-core",
        "image_ref": image_ref,
        "api_port": str(env.api_port),
        "container_port": str(env.api_port),
        "log_group": env.log_group,
        "aws_region": env.aws_region,
        "api_host": env.api_host,
        "origin_host": env.origin_host,
        "origin_port": str(env.origin_port),
    }
    values.update(github_app_deploy.github_app_render_values(env))
    project_root = _project_source_root(env.project, repo_path)
    compose_yaml = _render_service_template(
        project_root, "docker-compose.yml.tmpl", values
    )
    nginx_site = _render_service_template(
        project_root, "nginx-site.conf.tmpl", values
    )
    env_lines = [
        f"{DB_SECRET_ARN_ENV}={database.secret_arn}",
        f"{DB_SECRET_REGION_ENV}={database.region}",
        f"{DB_SECRET_HOST_ENV}={database.host}",
        f"{DB_SECRET_NAME_ENV}={database.database_name}",
        f"{DB_SECRET_PORT_ENV}={database.port}",
        f"YOKE_ENVIRONMENT={env.env_name}",
    ]
    if env.otel_exporter_endpoint:
        env_lines.append(f"OTEL_EXPORTER_OTLP_ENDPOINT={env.otel_exporter_endpoint}")
    env_lines.extend(github_app_deploy.github_app_env_lines(env))
    return compose_yaml, nginx_site, "\n".join(env_lines) + "\n"


def exec_core_container_deploy(
    project: str,
    env_name: str,
    *,
    repo_path: str = "",
    image_tag: str = "",
    runner: Optional[CommandRunner] = None,
    emit: Callable[[str], None] = _emit,
) -> int:
    """Run the full core-container deploy for ``project``/``env_name``."""
    runner = runner or CommandRunner()
    try:
        env = resolve_deploy_environment(project, env_name)
        if env.activation_state == "render_only":
            raise CoreDeployError(
                f"[core-deploy] environment '{env_name}' of project "
                f"'{project}' is declared render_only; activate its Pulumi "
                f"stack ({env.stack_name}) before deploying"
            )
        emit(
            f"  [core-deploy] target {env.project}/{env.env_name} "
            f"({env.origin_host}, stack {env.stack_name})"
        )

        aws_env = github_app_deploy.preflight(runner, env)
        tag = resolve_image_tag(
            runner, repo_path, image_tag, declared_branch=env.git_branch
        )
        if image_tag:
            emit(f"  [core-deploy] explicit image tag: {tag}")
        elif env.git_branch:
            emit(f"  [core-deploy] declared branch '{env.git_branch}' pinned to {tag}")
        else:
            emit(f"  [core-deploy] no declared branch; deploying repo HEAD {tag}")
        image_ref = ensure_image_in_registry(
            runner, env, aws_env, repo_path=repo_path, tag=tag, emit=emit
        )
        database, _outputs = resolve_environment_database_binding(
            runner, env, aws_env, repo_path=repo_path, emit=emit
        )
        compose_yaml, nginx_site, env_file = render_service_files(
            env, image_ref, database, repo_path=repo_path
        )
        ensure_runtime_packages(runner, env, emit)
        ensure_instance_profile(runner, env, emit)
        ensure_ecr_credential_helper(runner, env, emit)
        ensure_nginx_site(runner, env, nginx_site, emit)
        ensure_compose_project(runner, env, compose_yaml, env_file, emit)
        github_app_deploy.converge(runner, env)
        github_app_deploy.verify(runner, env, image_ref)
        compose_pull(runner, env, emit)
        verify_runtime_database_secret_access(runner, env, emit)
        prior_image_ref = capture_running_image_ref(runner, env, emit)
        compose_up(runner, env, emit)
        try:
            wait_container_healthy(runner, env, f"{env.deploy_namespace}-core", emit)
            request_id = str(uuid.uuid4())
            verify_origin_health(runner, env, request_id, tag, emit)
        except RemoteConvergenceError:
            # The swap completed but a health gate failed: one bounded
            # rollback to the pre-swap image, then the original failure
            # propagates — the stage fails either way.
            attempt_rollback(
                runner,
                env,
                prior_image_ref=prior_image_ref,
                failed_image_ref=image_ref,
                render_compose=lambda ref: render_service_files(
                    env, ref, database, repo_path=repo_path
                )[0],
                emit=emit,
            )
            raise
        _emit_deploy_event(env, image_ref, request_id)
        emit(f"  [core-deploy] {env.project}/{env.env_name} now running {image_ref}")
        # Post-health cleanup is fail-visible but does not roll back the
        # healthy container; rerunning the full deployment is idempotent.
        prune_superseded_images(
            runner,
            env,
            emit,
            keep_image_ref=image_ref,
            project_root=_project_source_root(env.project, repo_path),
        )
        return 0
    except (CoreDeployError, DeployEnvironmentError, RemoteConvergenceError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
