"""ephemeral-deploy executor — per-branch core-service preview environments.

Deployment-flow stage executor (``executor: "ephemeral-deploy"``) and the
operator CLI for the shared ephemeral substrate's core-service
instantiation: deploy any branch of a core-service project as an isolated
preview on the project's declared host environment box.

1. resolve the project's ephemeral policy (``ephemeral-env`` capability)
   and the host environment (:mod:`deploy_environment_settings`);
2. resolve the branch's local SHA and ensure the exact-SHA image exists in
   the project registry (:mod:`deploy_core_container_image`);
3. converge the host box preview substrate once (wildcard TLS, njs
   routing, TTL cleanup cron — :mod:`deploy_ephemeral_remote`);
4. converge the per-slug compose project: core container + disposable
   Postgres sidecar on a hash-derived localhost port;
5. bootstrap the disposable DB **inside the deployed image** (the
   branch's own ``environment_bootstrap`` chain), start the service, and
   gate on container health, on-box port health with x-request-id echo,
   then the public wildcard URL;
6. track the preview in ``ephemeral_environments``.

Webapp-shaped projects (Buzz) keep the GitHub-Actions instantiation of
the same substrate (``trigger: "github-push"``); this executor is the
``trigger: "flow"`` path and requires the core-service capabilities.

CLI::

    python3 -m yoke_core.domain.deploy_ephemeral <project> --branch B
        [--repo-path P] [--image-tag T] [--item LABEL] [--teardown]
"""

from __future__ import annotations

import argparse
import sys
import uuid
from typing import Callable, Optional

from yoke_core.domain.deploy_core_container_image import (
    CoreDeployError,
    ensure_image_in_registry,
)
from yoke_core.domain.deploy_core_container_remote import (
    RemoteConvergenceError,
    wait_container_healthy,
)
from yoke_core.domain.deploy_environment_activate import (
    EnvironmentActivateError,
    ensure_instance_running,
    wait_ssh_reachable,
)
from yoke_core.domain.deploy_environment_settings import (
    DeployEnvironmentError,
    resolve_deploy_environment,
)
from yoke_core.domain.deploy_ephemeral_files import (
    EphemeralDeployError,
    emit_ephemeral_event,
    render_webapp_template,
    routing_values,
    slug_files,
    track,
)
from yoke_core.domain.deploy_ephemeral_remote import (
    compose_bootstrap_and_up,
    converge_slug_project,
    ensure_cleanup_cron,
    ensure_preview_routing,
    ensure_wildcard_tls,
    generate_db_password,
    read_existing_db_password,
    teardown_slug_project,
    verify_slug_health,
)
from yoke_core.domain.deploy_remote import CommandRunner, aws_capability_env
from yoke_core.domain.ephemeral_substrate import (
    EphemeralPolicyError,
    compose_project_name,
    ephemeral_deploy_dir,
    load_ephemeral_policy,
    preview_url,
    slugify_branch,
)

_IMAGE_TAG_LENGTH = 12

_FAILURE_CLASSES = (
    EphemeralDeployError, EphemeralPolicyError, DeployEnvironmentError,
    CoreDeployError, RemoteConvergenceError, EnvironmentActivateError,
)


def _emit(line: str) -> None:
    print(line, flush=True)


def _resolve_branch_sha(
    runner: CommandRunner, repo_path: str, branch: str
) -> str:
    """The branch's local commit SHA — the worktree tier deploys local code."""
    if not repo_path:
        raise EphemeralDeployError(
            "[ephemeral] no project repo path available to resolve the "
            "branch SHA"
        )
    result = runner.run(
        ["git", "-C", repo_path, "rev-parse", branch], timeout=30
    )
    if not result.ok or not result.stdout.strip():
        raise EphemeralDeployError(
            f"[ephemeral] could not resolve branch '{branch}' in "
            f"{repo_path}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def exec_ephemeral_deploy(
    project: str,
    *,
    branch: str = "",
    repo_path: str = "",
    image_tag: str = "",
    item_label: str = "",
    runner: Optional[CommandRunner] = None,
    emit: Callable[[str], None] = _emit,
) -> int:
    """Deploy *branch* of *project* as an isolated preview environment."""
    runner = runner or CommandRunner()
    slug = ""
    try:
        if not branch:
            raise EphemeralDeployError(
                "[ephemeral] no branch to deploy: run item-bound (the item's "
                "worktree branch) or pass --branch to "
                "python3 -m yoke_core.domain.deploy_ephemeral"
            )
        policy = load_ephemeral_policy(project)
        env = resolve_deploy_environment(policy.project, policy.host_env)
        if env.activation_state == "render_only":
            raise EphemeralDeployError(
                f"[ephemeral] host environment '{policy.host_env}' of "
                f"project '{policy.project}' is declared render_only; "
                f"activate its Pulumi stack ({env.stack_name}) first"
            )
        slug = slugify_branch(branch)
        api_port = policy.api_port_for(slug)
        url = preview_url(slug, policy.preview_domain)
        deploy_dir = ephemeral_deploy_dir(policy.project, slug)
        emit(
            f"  [ephemeral] target {policy.project}/{slug} on host env "
            f"{policy.host_env} ({env.origin_host}, port {api_port})"
        )

        sha = _resolve_branch_sha(runner, repo_path, branch)
        tag = image_tag or sha[:_IMAGE_TAG_LENGTH]
        aws_env = aws_capability_env(policy.project, env.aws_region)
        ensure_instance_running(runner, env, aws_env, emit)
        wait_ssh_reachable(runner, env, emit)
        image_ref = ensure_image_in_registry(
            runner, env, aws_env, repo_path=repo_path, tag=tag, emit=emit
        )

        ensure_wildcard_tls(runner, env, policy.preview_domain, emit)
        routing = routing_values(policy)
        ensure_preview_routing(
            runner, env,
            render_webapp_template("ops/nginx-ephemeral.conf", routing),
            render_webapp_template("ops/ephemeral_port.js", routing),
            emit,
        )
        ensure_cleanup_cron(
            runner, env,
            render_webapp_template("ops/ephemeral-cleanup.sh.tmpl", routing),
            emit,
        )

        db_password = (
            read_existing_db_password(runner, env, deploy_dir)
            or generate_db_password()
        )
        compose_yaml, env_file, dsn = slug_files(
            policy, env, slug, image_ref, api_port, db_password
        )
        track(
            policy.project, branch,
            {"port_api": str(api_port), "url": url, "deployed_sha": sha},
            item_label=item_label,
        )
        converge_slug_project(
            runner, env, deploy_dir, compose_yaml, env_file, dsn,
            db_password, emit,
        )
        compose_bootstrap_and_up(runner, env, deploy_dir, emit)
        wait_container_healthy(
            runner, env,
            f"{compose_project_name(policy.project, slug)}-core", emit,
        )

        verify_slug_health(
            runner, env, api_port, env.health_path, str(uuid.uuid4()), emit
        )
        from yoke_core.tools import executors as _executors

        public_rc = _executors.exec_health_check(
            url + env.health_path, request_id=str(uuid.uuid4())
        )
        if public_rc != 0:
            raise EphemeralDeployError(
                f"[ephemeral] public preview health check failed for {url}"
                f"{env.health_path}; wildcard DNS/TLS/routing is part of "
                "the deploy contract"
            )
        track(
            policy.project, branch,
            {"status": "running", "health_check_url": url + env.health_path},
            item_label=item_label,
        )
        emit_ephemeral_event(
            "DeploymentEphemeralDeployed", policy, slug,
            {"url": url, "image_ref": image_ref, "branch": branch},
        )
        emit(f"  [ephemeral] {policy.project}/{slug} now serving {url}")
        return 0
    except _FAILURE_CLASSES as exc:
        if slug:
            try:
                track(project, branch, {"status": "failed"})
            except Exception:
                pass
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


def exec_ephemeral_teardown(
    project: str,
    *,
    branch: str = "",
    runner: Optional[CommandRunner] = None,
    emit: Callable[[str], None] = _emit,
) -> int:
    """Tear down *branch*'s preview: compose down, volumes, dir, DB row."""
    runner = runner or CommandRunner()
    try:
        if not branch:
            raise EphemeralDeployError(
                "[ephemeral] --branch is required for teardown"
            )
        policy = load_ephemeral_policy(project)
        env = resolve_deploy_environment(policy.project, policy.host_env)
        slug = slugify_branch(branch)
        teardown_slug_project(
            runner, env,
            ephemeral_deploy_dir(policy.project, slug),
            compose_project_name(policy.project, slug),
            emit,
        )
        track(policy.project, branch, {"status": "stopped"})
        emit_ephemeral_event(
            "DeploymentEphemeralTorndown", policy, slug, {"branch": branch}
        )
        return 0
    except _FAILURE_CLASSES as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="deploy-ephemeral",
        description=(
            "Deploy (or tear down) a branch of a core-service project as "
            "an isolated preview environment on its declared host env box."
        ),
    )
    parser.add_argument("project")
    parser.add_argument("--branch", required=True)
    parser.add_argument("--repo-path", default=".")
    parser.add_argument("--image-tag", default="")
    parser.add_argument("--item", default="", help="item label for tracking")
    parser.add_argument("--teardown", action="store_true")
    args = parser.parse_args(argv)
    if args.teardown:
        return exec_ephemeral_teardown(args.project, branch=args.branch)
    return exec_ephemeral_deploy(
        args.project,
        branch=args.branch,
        repo_path=args.repo_path,
        image_tag=args.image_tag,
        item_label=args.item,
    )


if __name__ == "__main__":
    sys.exit(main())
