"""Origin-owned GitHub App key retrieval and verification."""

from __future__ import annotations

import shlex
from typing import Any

GITHUB_APP_PRIVATE_KEY_FILE_NAME = "github-app-private-key.pem"
GITHUB_APP_PRIVATE_KEY_PENDING_FILE_NAME = (
    f".{GITHUB_APP_PRIVATE_KEY_FILE_NAME}.pending"
)
GITHUB_APP_PRIVATE_KEY_SECRET_NAME = "yoke-github-app-private-key"
GITHUB_APP_PRIVATE_KEY_CONTAINER_PATH = (
    f"/run/secrets/{GITHUB_APP_PRIVATE_KEY_SECRET_NAME}"
)


def converge_from_instance_role(runner: Any, env: Any) -> None:
    """Fetch the environment key on the origin without crossing CI."""
    from yoke_core.domain.deploy_core_container_remote import (
        RemoteConvergenceError,
    )
    from yoke_core.domain.deploy_remote import remove_remote_file, run_remote

    remote_path = f"{env.compose_dir}/{GITHUB_APP_PRIVATE_KEY_FILE_NAME}"
    pending_path = (
        f"{env.compose_dir}/{GITHUB_APP_PRIVATE_KEY_PENDING_FILE_NAME}"
    )
    if env.github_app is None:
        for selected_path in (remote_path, pending_path):
            removed = remove_remote_file(
                runner,
                env,
                remote_path=selected_path,
                sudo=False,
                timeout=30,
            )
            if not removed.ok:
                raise RemoteConvergenceError(
                    "[core-deploy] stale GitHub App private-key cleanup failed "
                    f"(rc={removed.returncode})"
                )
        return

    directory = shlex.quote(env.compose_dir)
    pending = shlex.quote(pending_path)
    template = shlex.quote(
        f"{env.compose_dir}/.{GITHUB_APP_PRIVATE_KEY_FILE_NAME}.XXXXXX"
    )
    secret_arn = shlex.quote(env.github_app.private_key_secret_arn)
    region = shlex.quote(env.aws_region)
    command = (
        "set -eu; umask 077; "
        f"mkdir -p {directory}; "
        f"tmp=$(mktemp {template}); "
        "trap 'rm -f \"$tmp\"' EXIT HUP INT TERM; "
        "aws secretsmanager get-secret-value --no-cli-pager "
        f"--region {region} --secret-id {secret_arn} "
        "--query SecretString --output text >\"$tmp\"; "
        "test -s \"$tmp\"; chmod 600 \"$tmp\"; "
        f"mv -f \"$tmp\" {pending}; trap - EXIT HUP INT TERM"
    )
    result = run_remote(runner, env, command, timeout=60)
    if not result.ok:
        raise RemoteConvergenceError(
            "[core-deploy] origin GitHub App private-key resolution failed "
            f"(rc={result.returncode}); apply {env.stack_name} so its instance "
            "role can read the environment's exact secret ARN"
        )


def verification_and_promotion_command(env: Any, image_ref: str) -> str:
    """Build the origin-only verify-then-promote rotation command."""
    directory = shlex.quote(env.compose_dir)
    pending_path = (
        f"{env.compose_dir}/{GITHUB_APP_PRIVATE_KEY_PENDING_FILE_NAME}"
    )
    final_path = f"{env.compose_dir}/{GITHUB_APP_PRIVATE_KEY_FILE_NAME}"
    pending = shlex.quote(pending_path)
    final = shlex.quote(final_path)
    image = shlex.quote(image_ref)
    issuer = shlex.quote(env.github_app.issuer)
    api_url = shlex.quote(env.github_app.api_url)
    probe_path = "/run/yoke/github-app-private-key-pending.pem"
    return (
        f"cd {directory} && "
        f"if docker pull {image} >/dev/null && docker run --rm "
        f"-e YOKE_GITHUB_APP_ISSUER={issuer} "
        f"-e YOKE_GITHUB_APP_API_URL={api_url} "
        f"-e YOKE_GITHUB_APP_PRIVATE_KEY_FILE={probe_path} "
        f"-v {pending}:{probe_path}:ro "
        f"--entrypoint python {image} -m yoke_core.tools.github_app_identity_probe; "
        f"then chmod 600 {pending} && mv -f {pending} {final}; "
        f"else rm -f {pending}; exit 1; fi"
    )


def verify_and_promote_in_core_image(
    runner: Any, env: Any, image_ref: str,
) -> None:
    """Verify the pending key, then atomically replace the durable key."""
    from yoke_core.domain.deploy_core_container_remote import (
        RemoteConvergenceError,
    )
    from yoke_core.domain.deploy_remote import run_remote

    if env.github_app is None:
        return
    result = run_remote(
        runner,
        env,
        verification_and_promotion_command(env, image_ref),
        timeout=90,
    )
    if not result.ok:
        raise RemoteConvergenceError(
            "[core-deploy] origin GitHub App issuer/private-key verification "
            f"failed for {env.env_name} (rc={result.returncode})"
        )


__all__ = [
    "GITHUB_APP_PRIVATE_KEY_CONTAINER_PATH",
    "GITHUB_APP_PRIVATE_KEY_FILE_NAME",
    "GITHUB_APP_PRIVATE_KEY_PENDING_FILE_NAME",
    "GITHUB_APP_PRIVATE_KEY_SECRET_NAME",
    "converge_from_instance_role",
    "verification_and_promotion_command",
    "verify_and_promote_in_core_image",
]
