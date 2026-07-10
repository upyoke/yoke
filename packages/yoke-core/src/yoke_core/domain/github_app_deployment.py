"""Environment-scoped GitHub App secret delivery for core deployments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    validate_github_api_endpoint,
)
from yoke_core.domain.github_app_control_plane import (
    GitHubAppControlPlaneConfigError,
    validate_github_app_issuer,
)
from yoke_core.domain.github_app_remote_identity import (
    GitHubAppIdentity,
    GitHubAppIdentityVerificationError,
    verify_github_app_identity,
)


GITHUB_APP_PRIVATE_KEY_FILE_NAME = "github-app-private-key.pem"
GITHUB_APP_PRIVATE_KEY_SECRET_NAME = "yoke-github-app-private-key"
GITHUB_APP_PRIVATE_KEY_CONTAINER_PATH = (
    f"/run/secrets/{GITHUB_APP_PRIVATE_KEY_SECRET_NAME}"
)


class GitHubAppDeploymentConfigError(ValueError):
    """Environment GitHub App settings are incomplete or unsafe."""


@dataclass(frozen=True)
class GitHubAppDeploymentConfig:
    """Nonsecret environment settings plus one managed-secret reference."""

    issuer: str
    api_url: str
    private_key_secret_arn: str


def github_app_config_from_environment_settings(
    env_settings: Mapping[str, Any],
    *,
    env_hint: str,
) -> GitHubAppDeploymentConfig | None:
    """Parse an optional ``environments.settings.github_app`` block."""
    raw = env_settings.get("github_app")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise GitHubAppDeploymentConfigError(
            f"environments.settings.github_app must be an object; {env_hint}"
        )
    selected = {
        "issuer": str(raw.get("issuer") or "").strip(),
        "api_url": str(raw.get("api_url") or "").strip(),
        "private_key_secret_arn": str(raw.get("private_key_secret_arn") or "").strip(),
    }
    missing = [key for key, value in selected.items() if not value]
    if missing:
        raise GitHubAppDeploymentConfigError(
            "environments.settings.github_app is incomplete; missing "
            f"{', '.join(missing)}; {env_hint}"
        )
    try:
        selected["issuer"] = validate_github_app_issuer(selected["issuer"])
    except GitHubAppControlPlaneConfigError as exc:
        raise GitHubAppDeploymentConfigError(
            "environments.settings.github_app.issuer must be a GitHub App "
            f"client id or numeric app id; {env_hint}"
        ) from exc
    try:
        api_url = validate_github_api_endpoint(selected["api_url"]).base_url
    except GitHubApiOriginError as exc:
        raise GitHubAppDeploymentConfigError(
            f"environments.settings.github_app.api_url is invalid: {exc}; {env_hint}"
        ) from exc
    secret_arn = selected["private_key_secret_arn"]
    if not secret_arn.startswith("arn:aws:secretsmanager:"):
        raise GitHubAppDeploymentConfigError(
            "environments.settings.github_app.private_key_secret_arn must be "
            f"an AWS Secrets Manager ARN; {env_hint}"
        )
    return GitHubAppDeploymentConfig(
        issuer=selected["issuer"],
        api_url=api_url,
        private_key_secret_arn=secret_arn,
    )


def github_app_render_values(env: Any) -> dict[str, str]:
    """Return the optional Compose mount fragment for ``env``."""
    if env.github_app is None:
        return {
            "github_app_secret_mount": "",
            "github_app_secret_definition": "",
        }
    return {
        "github_app_secret_mount": (
            f"    secrets:\n      - {GITHUB_APP_PRIVATE_KEY_SECRET_NAME}"
        ),
        "github_app_secret_definition": (
            "secrets:\n"
            f"  {GITHUB_APP_PRIVATE_KEY_SECRET_NAME}:\n"
            f"    file: ./{GITHUB_APP_PRIVATE_KEY_FILE_NAME}"
        ),
    }


def github_app_env_lines(env: Any) -> list[str]:
    """Return nonsecret runtime bindings for the mounted App key."""
    if env.github_app is None:
        return []
    from yoke_core.domain.github_app_control_plane import (
        GITHUB_APP_API_URL_ENV,
        GITHUB_APP_ISSUER_ENV,
        GITHUB_APP_PRIVATE_KEY_FILE_ENV,
    )

    return [
        f"{GITHUB_APP_ISSUER_ENV}={env.github_app.issuer}",
        f"{GITHUB_APP_API_URL_ENV}={env.github_app.api_url}",
        f"{GITHUB_APP_PRIVATE_KEY_FILE_ENV}={GITHUB_APP_PRIVATE_KEY_CONTAINER_PATH}",
    ]


def preflight_github_app_private_key(
    runner: Any,
    env: Any,
    aws_env: Mapping[str, str],
    *,
    secret_loader: Any = None,
    identity_verifier: Any = None,
) -> str | None:
    """Load and verify the configured App key without mutating the host."""
    from yoke_core.domain.deploy_core_container_remote import (
        RemoteConvergenceError,
    )

    if env.github_app is None:
        return None
    if secret_loader is None:
        from yoke_core.domain.yoke_cloud_db_authority import load_secret_string

        secret_loader = load_secret_string
    if identity_verifier is None:
        identity_verifier = verify_github_app_identity

    try:
        private_key = secret_loader(
            env.github_app.private_key_secret_arn,
            region=env.aws_region,
            env=aws_env,
        ).strip()
    except Exception as exc:
        raise RemoteConvergenceError(
            "[core-deploy] GitHub App private-key secret resolution failed for "
            f"{env.env_name}: {exc}"
        ) from exc
    if not private_key:
        raise RemoteConvergenceError(
            "[core-deploy] GitHub App private-key secret resolved empty for "
            f"{env.env_name}"
        )
    try:
        identity_verifier(
            runner=runner,
            env=env,
            issuer=env.github_app.issuer,
            private_key_pem=private_key,
            api_url=env.github_app.api_url,
        )
    except Exception as exc:
        raise RemoteConvergenceError(
            "[core-deploy] GitHub App issuer/private-key verification failed "
            f"for {env.env_name}"
        ) from exc
    return private_key


def converge_github_app_private_key(
    runner: Any,
    env: Any,
    *,
    private_key_pem: str | None,
    file_pusher: Any = None,
) -> None:
    """Atomically deliver a preflight-verified key through SSH stdin."""
    from yoke_core.domain.deploy_core_container_remote import (
        RemoteConvergenceError,
    )
    from yoke_core.domain.deploy_remote import remove_remote_file

    remote_path = f"{env.compose_dir}/{GITHUB_APP_PRIVATE_KEY_FILE_NAME}"
    if env.github_app is None:
        removed = remove_remote_file(
            runner,
            env,
            remote_path=remote_path,
            sudo=False,
            timeout=30,
        )
        if not removed.ok:
            raise RemoteConvergenceError(
                "[core-deploy] stale GitHub App private-key cleanup failed "
                f"(rc={removed.returncode})"
            )
        return
    if not private_key_pem:
        raise RemoteConvergenceError(
            "[core-deploy] GitHub App private key was not prepared by preflight"
        )
    if file_pusher is None:
        from yoke_core.domain.deploy_remote import push_remote_file

        file_pusher = push_remote_file
    pushed = file_pusher(
        runner,
        env,
        content=private_key_pem,
        remote_path=remote_path,
        mode="600",
        sudo=False,
    )
    if not pushed.ok:
        raise RemoteConvergenceError(
            "[core-deploy] GitHub App private-key file write failed "
            f"(rc={pushed.returncode})"
        )


__all__ = [
    "GITHUB_APP_PRIVATE_KEY_CONTAINER_PATH",
    "GITHUB_APP_PRIVATE_KEY_FILE_NAME",
    "GITHUB_APP_PRIVATE_KEY_SECRET_NAME",
    "GitHubAppDeploymentConfig",
    "GitHubAppDeploymentConfigError",
    "GitHubAppIdentity",
    "GitHubAppIdentityVerificationError",
    "converge_github_app_private_key",
    "github_app_config_from_environment_settings",
    "github_app_env_lines",
    "github_app_render_values",
    "preflight_github_app_private_key",
    "verify_github_app_identity",
]
