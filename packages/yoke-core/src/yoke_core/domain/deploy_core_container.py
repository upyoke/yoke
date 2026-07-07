"""core-container-deploy executor — deploy the Yoke core container to an env.

Deployment-flow stage executor (``executor: "core-container-deploy"``) that
takes one project environment from DB-declared authority to a running,
healthy core-service container:

1. resolve the environment + capabilities (:mod:`deploy_environment_settings`);
2. ensure the image for the requested tag exists in the project container
   registry (:mod:`deploy_core_container_image`);
3. resolve the env's Postgres DSN from Pulumi stack outputs + the
   RDS-managed secret (reusing :mod:`yoke_cloud_db_authority`);
4. converge the origin host idempotently (docker/nginx/ECR helper/compose
   project — :mod:`deploy_core_container_remote`);
5. pull + start the container, then gate on container health, then the
   origin nginx health endpoint with x-request-id echo (request-id propagation contract).
   A health-gate failure after the swap triggers one bounded rollback to
   the pre-swap image (:mod:`deploy_core_container_rollback`); the stage
   still fails — rollback restores service, never success.

Secrets only ever travel via subprocess env or SSH stdin; every emitted
line is redaction-safe. The executor prints ``[core-deploy]``-prefixed
progress lines (with ERROR markers on failure) for stream filters.
"""

from __future__ import annotations

import sys
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
from yoke_core.domain.deploy_remote import CommandRunner, aws_capability_env
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


def _render_service_template(name: str, values: dict) -> str:
    from yoke_core.domain.project_renderer import render_template
    from yoke_core.api.repo_root import find_repo_root

    template = (
        find_repo_root(Path(__file__))
        / "templates" / "webapp" / "core-service" / name
    )
    if not template.is_file():
        raise CoreDeployError(
            f"[core-deploy] service template missing: {template}"
        )
    return render_template(template.read_text(), values)


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
    emit: Callable[[str], None] = _emit,
) -> tuple[RuntimeDatabaseBinding, dict]:
    """Resolve the env's endpoint + secret ARN from stack outputs."""
    from yoke_core.domain.project_renderer import default_render_output_dir

    # The render subprocess gets an explicit --output-dir computed HERE:
    # the scratch-backed default is pid-scoped, so letting the subprocess
    # pick its own default would land the render in the child's run dir
    # while this process reads a sibling path that never existed.
    out_dir = default_render_output_dir(env.project)
    render = runner.run(
        [
            sys.executable, "-m", "yoke_core.tools.render_project",
            env.project, "--write", "--only", "pulumi",
            "--output-dir", str(out_dir),
        ],
        timeout=300,
    )
    if not render.ok:
        raise CoreDeployError(
            "[core-deploy] project Pulumi render failed: "
            + (render.stderr or render.stdout).strip()[-800:]
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
    emit: Callable[[str], None] = _emit,
) -> tuple[RuntimeDatabaseBinding, dict]:
    """Resolve the non-secret DB binding the container uses at runtime."""
    return _load_environment_stack_binding(runner, env, aws_env, emit=emit)


def resolve_environment_dsn(
    runner: CommandRunner,
    env: DeployEnvironment,
    aws_env: dict,
    *,
    emit: Callable[[str], None] = _emit,
) -> tuple[str, dict]:
    """Resolve the env's libpq DSN from stack outputs + Secrets Manager.

    Also returns the full (non-secret) stack outputs mapping so callers can
    reuse facts like the instance id without a second Pulumi roundtrip.
    """
    binding, outputs = _load_environment_stack_binding(
        runner, env, aws_env, emit=emit
    )
    try:
        secret = PostgresSecret.from_json(
            load_secret_string(
                binding.secret_arn, region=binding.region, env=aws_env
            )
        )
    except Exception as exc:
        raise CoreDeployError(
            f"[core-deploy] env DSN resolution failed for stack "
            f"{env.stack_name}: {exc}"
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
) -> tuple[str, str, str]:
    """Render (compose_yaml, nginx_site, env_file) for the target env.

    The env file is deliberately password-free: it carries the RDS-managed
    secret ARN plus endpoint facts, and the container resolves the current
    password from Secrets Manager at connection time.
    """
    values = {
        "project": env.project,
        "env_name": env.env_name,
        "container_name": f"{env.project}-core",
        "image_ref": image_ref,
        "api_port": str(env.api_port),
        "container_port": str(env.api_port),
        "log_group": env.log_group,
        "aws_region": env.aws_region,
        "api_host": env.api_host,
        "origin_host": env.origin_host,
        "origin_port": str(env.origin_port),
    }
    compose_yaml = _render_service_template("docker-compose.yml.tmpl", values)
    nginx_site = _render_service_template("nginx-site.conf.tmpl", values)
    env_lines = [
        f"{DB_SECRET_ARN_ENV}={database.secret_arn}",
        f"{DB_SECRET_REGION_ENV}={database.region}",
        f"{DB_SECRET_HOST_ENV}={database.host}",
        f"{DB_SECRET_NAME_ENV}={database.database_name}",
        f"{DB_SECRET_PORT_ENV}={database.port}",
        f"YOKE_ENVIRONMENT={env.env_name}",
    ]
    if env.otel_exporter_endpoint:
        env_lines.append(
            f"OTEL_EXPORTER_OTLP_ENDPOINT={env.otel_exporter_endpoint}"
        )
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

        aws_env = aws_capability_env(env.project, env.aws_region)
        tag = resolve_image_tag(
            runner, repo_path, image_tag, declared_branch=env.git_branch
        )
        if image_tag:
            emit(f"  [core-deploy] explicit image tag: {tag}")
        elif env.git_branch:
            emit(
                f"  [core-deploy] declared branch '{env.git_branch}' "
                f"pinned to {tag}"
            )
        else:
            emit(
                f"  [core-deploy] no declared branch; deploying repo HEAD {tag}"
            )
        image_ref = ensure_image_in_registry(
            runner, env, aws_env, repo_path=repo_path, tag=tag, emit=emit
        )
        database, _outputs = resolve_environment_database_binding(
            runner, env, aws_env, emit=emit
        )
        compose_yaml, nginx_site, env_file = render_service_files(
            env, image_ref, database
        )

        ensure_runtime_packages(runner, env, emit)
        ensure_instance_profile(runner, env, emit)
        ensure_ecr_credential_helper(runner, env, emit)
        ensure_nginx_site(runner, env, nginx_site, emit)
        ensure_compose_project(runner, env, compose_yaml, env_file, emit)
        compose_pull(runner, env, emit)
        verify_runtime_database_secret_access(runner, env, emit)
        prior_image_ref = capture_running_image_ref(runner, env, emit)
        compose_up(runner, env, emit)
        try:
            wait_container_healthy(runner, env, f"{env.project}-core", emit)
            request_id = str(uuid.uuid4())
            verify_origin_health(runner, env, request_id, emit)
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
                    env, ref, database
                )[0],
                emit=emit,
            )
            raise
        _emit_deploy_event(env, image_ref, request_id)
        emit(
            f"  [core-deploy] {env.project}/{env.env_name} now running "
            f"{image_ref}"
        )
        # New image is live + health-verified: reclaim disk from superseded
        # images so the origin box's small root volume never fills across
        # repeated auto-deploys. Best-effort — never fails a live deploy.
        prune_superseded_images(runner, env, emit)
        return 0
    except (CoreDeployError, DeployEnvironmentError, RemoteConvergenceError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


def _emit_deploy_event(
    env: DeployEnvironment, image_ref: str, request_id: str
) -> None:
    """Record the deploy through the canonical emitter (best-effort)."""
    try:
        from yoke_core.domain.events import emit_event

        emit_event(
            "DeploymentCoreContainerDeployed",
            event_kind="lifecycle",
            event_type="deployment_run",
            source_type="system",
            severity="STATUS",
            project=env.project,
            outcome="completed",
            environment=env.env_name,
            request_id=request_id,
            context={
                "image_ref": image_ref,
                "origin_host": env.origin_host,
                "log_group": env.log_group,
            },
        )
    except Exception as exc:  # pragma: no cover - telemetry is best-effort
        print(
            f"  [core-deploy] warning: deploy event emission failed: {exc}",
            file=sys.stderr,
        )
