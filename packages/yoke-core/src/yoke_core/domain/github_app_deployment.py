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
from yoke_core.domain.github_app_origin_key import (
    GITHUB_APP_PRIVATE_KEY_CONTAINER_PATH,
    GITHUB_APP_PRIVATE_KEY_FILE_NAME,
    GITHUB_APP_PRIVATE_KEY_SECRET_NAME,
)


class GitHubAppDeploymentConfigError(ValueError):
    """Environment GitHub App settings are incomplete or unsafe."""


@dataclass(frozen=True)
class GitHubAppDeploymentConfig:
    """Nonsecret environment settings plus one managed-secret reference."""

    issuer: str
    api_url: str
    private_key_secret_arn: str
    kms_key_arn: str = ""


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
    kms_key_arn = str(raw.get("kms_key_arn") or "").strip()
    if kms_key_arn and not kms_key_arn.startswith("arn:aws:kms:"):
        raise GitHubAppDeploymentConfigError(
            "environments.settings.github_app.kms_key_arn must be an AWS "
            f"KMS key ARN when set; {env_hint}"
        )
    return GitHubAppDeploymentConfig(
        issuer=selected["issuer"],
        api_url=api_url,
        private_key_secret_arn=secret_arn,
        kms_key_arn=kms_key_arn,
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


__all__ = [
    "GITHUB_APP_PRIVATE_KEY_CONTAINER_PATH",
    "GITHUB_APP_PRIVATE_KEY_FILE_NAME",
    "GITHUB_APP_PRIVATE_KEY_SECRET_NAME",
    "GitHubAppDeploymentConfig",
    "GitHubAppDeploymentConfigError",
    "github_app_config_from_environment_settings",
    "github_app_env_lines",
    "github_app_render_values",
]
