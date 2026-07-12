"""Origin-owned GitHub App key retrieval and verification."""

from __future__ import annotations

import shlex
from typing import Any

from yoke_contracts.github_app_public import (
    GITHUB_APP_CLIENT_ID_ENV,
    GITHUB_APP_ID_ENV,
    GITHUB_APP_SLUG_ENV,
    GITHUB_APP_WEB_URL_ENV,
)

GITHUB_APP_PRIVATE_KEY_FILE_NAME = "github-app-private-key.pem"
GITHUB_APP_PRIVATE_KEY_PENDING_FILE_NAME = (
    f".{GITHUB_APP_PRIVATE_KEY_FILE_NAME}.pending"
)
GITHUB_APP_PRIVATE_KEY_SECRET_NAME = "yoke-github-app-private-key"
GITHUB_APP_SECRET_GROUP_NAME = "yoke-core-secrets"
GITHUB_APP_SECRET_GID_ENV = "YOKE_GITHUB_APP_SECRET_GID"
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
    pending_path = f"{env.compose_dir}/{GITHUB_APP_PRIVATE_KEY_PENDING_FILE_NAME}"
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
    env_file = shlex.quote(f"{env.compose_dir}/.env")
    pending = shlex.quote(pending_path)
    template = shlex.quote(
        f"{env.compose_dir}/.{GITHUB_APP_PRIVATE_KEY_FILE_NAME}.XXXXXX"
    )
    secret_arn = shlex.quote(env.github_app.private_key_secret_arn)
    region = shlex.quote(env.aws_region)
    secret_group = shlex.quote(GITHUB_APP_SECRET_GROUP_NAME)
    command = (
        "set -eu; umask 077; "
        f"mkdir -p {directory}; "
        f"if ! getent group {secret_group} >/dev/null 2>&1; then "
        f"sudo groupadd --system {secret_group}; fi; "
        f"secret_gid=$(getent group {secret_group} | cut -d: -f3); "
        'test -n "$secret_gid"; '
        f"sed -i '/^{GITHUB_APP_SECRET_GID_ENV}=/d' {env_file}; "
        f"printf '{GITHUB_APP_SECRET_GID_ENV}=%s\\n' \"$secret_gid\" >>{env_file}; "
        f"chmod 600 {env_file}; "
        f"tmp=$(mktemp {template}); "
        "trap 'rm -f \"$tmp\"' EXIT HUP INT TERM; "
        "aws secretsmanager get-secret-value --no-cli-pager "
        f"--region {region} --secret-id {secret_arn} "
        '--query SecretString --output text >"$tmp"; '
        'test -s "$tmp"; sudo chgrp "$secret_gid" "$tmp"; '
        'chmod 640 "$tmp"; '
        f'mv -f "$tmp" {pending}; trap - EXIT HUP INT TERM'
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
    pending_path = f"{env.compose_dir}/{GITHUB_APP_PRIVATE_KEY_PENDING_FILE_NAME}"
    final_path = f"{env.compose_dir}/{GITHUB_APP_PRIVATE_KEY_FILE_NAME}"
    pending = shlex.quote(pending_path)
    final = shlex.quote(final_path)
    image = shlex.quote(image_ref)
    issuer = shlex.quote(env.github_app.issuer)
    api_url = shlex.quote(env.github_app.api_url)
    secret_group = shlex.quote(GITHUB_APP_SECRET_GROUP_NAME)
    probe_path = "/run/yoke/github-app-private-key-pending.pem"
    public_env = _public_identity_probe_env(env)
    return (
        f"cd {directory} && "
        f"if secret_gid=$(getent group {secret_group} | cut -d: -f3) "
        '&& test -n "$secret_gid" '
        f"&& docker pull {image} >/dev/null && docker run --rm "
        '--group-add "$secret_gid" '
        f"-e YOKE_GITHUB_APP_ISSUER={issuer} "
        f"-e YOKE_GITHUB_APP_API_URL={api_url} "
        f"-e YOKE_GITHUB_APP_PRIVATE_KEY_FILE={probe_path} "
        f"{public_env}"
        f"-v {pending}:{probe_path}:ro "
        f"--entrypoint python {image} -m yoke_core.tools.github_app_identity_probe; "
        f"then chmod 640 {pending} && mv -f {pending} {final}; "
        f"else rm -f {pending}; exit 1; fi"
    )


def _public_identity_probe_env(env: Any) -> str:
    profile = getattr(env.github_app, "public_profile", None)
    if profile is None:
        return ""
    values = (
        (GITHUB_APP_CLIENT_ID_ENV, profile.client_id),
        (GITHUB_APP_SLUG_ENV, profile.app_slug),
        (GITHUB_APP_ID_ENV, str(profile.app_id)),
        (GITHUB_APP_WEB_URL_ENV, profile.web_url),
    )
    return "".join(f"-e {name}={shlex.quote(value)} " for name, value in values)


def verify_and_promote_in_core_image(
    runner: Any,
    env: Any,
    image_ref: str,
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
    "GITHUB_APP_SECRET_GID_ENV",
    "GITHUB_APP_SECRET_GROUP_NAME",
    "converge_from_instance_role",
    "verification_and_promotion_command",
    "verify_and_promote_in_core_image",
]
