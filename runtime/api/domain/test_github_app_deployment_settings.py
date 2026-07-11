"""Environment GitHub App settings and nonsecret Compose bindings."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_deploy_core_container import _BINDING, _env
from yoke_core.domain import github_app_deployment
from yoke_core.domain.deploy_core_container import render_service_files

_APP_CONFIG = github_app_deployment.GitHubAppDeploymentConfig(
    issuer="123456",
    api_url="https://api.github.com",
    private_key_secret_arn=(
        "arn:aws:secretsmanager:us-east-1:123:"
        "secret:yoke/prod/github-app-private-key-AbCdEf"
    ),
)


def test_github_app_config_rejects_env_line_injection():
    with pytest.raises(
        github_app_deployment.GitHubAppDeploymentConfigError,
        match="issuer must be",
    ):
        github_app_deployment.github_app_config_from_environment_settings(
            {
                "github_app": {
                    "issuer": "123\nYOKE_INJECTED=value",
                    "api_url": "https://api.github.com",
                    "private_key_secret_arn": (
                        "arn:aws:secretsmanager:us-east-1:123:secret:github"
                    ),
                }
            },
            env_hint="configure stage",
        )


def test_github_app_config_mounts_owner_only_key_reference():
    compose, _, env_file = render_service_files(
        _env(github_app=_APP_CONFIG), "img:tag", _BINDING
    )

    assert "secrets:\n      - yoke-github-app-private-key" in compose
    assert "group_add:" in compose
    assert "YOKE_GITHUB_APP_SECRET_GID is required" in compose
    assert "file: ./github-app-private-key.pem" in compose
    assert "YOKE_GITHUB_APP_ISSUER=123456" in env_file
    assert "YOKE_GITHUB_APP_API_URL=https://api.github.com" in env_file
    assert (
        "YOKE_GITHUB_APP_PRIVATE_KEY_FILE=/run/secrets/yoke-github-app-private-key"
    ) in env_file
    assert _APP_CONFIG.private_key_secret_arn not in compose + env_file


def test_github_app_config_accepts_exact_optional_kms_key_arn():
    config = github_app_deployment.github_app_config_from_environment_settings(
        {
            "github_app": {
                "issuer": "123456",
                "api_url": "https://api.github.com",
                "private_key_secret_arn": _APP_CONFIG.private_key_secret_arn,
                "kms_key_arn": (
                    "arn:aws:kms:us-east-1:123:key/11111111-2222-3333-4444-555555555555"
                ),
            }
        },
        env_hint="configure prod",
    )

    assert config is not None
    assert config.kms_key_arn.endswith("555555555555")


def test_public_profile_is_optional_complete_and_rendered():
    private_only = github_app_deployment.github_app_config_from_environment_settings(
        {
            "github_app": {
                "issuer": "123456",
                "api_url": "https://api.github.com",
                "private_key_secret_arn": _APP_CONFIG.private_key_secret_arn,
            }
        },
        env_hint="configure prod",
    )
    assert private_only is not None
    assert private_only.public_profile is None

    advertised = github_app_deployment.github_app_config_from_environment_settings(
        {
            "github_app": {
                "issuer": "123456",
                "api_url": "https://api.github.com",
                "private_key_secret_arn": _APP_CONFIG.private_key_secret_arn,
                "public": {
                    "client_id": "Iv23public",
                    "app_slug": "yoke-development",
                    "app_id": 123456,
                    "web_url": "https://github.com",
                },
            }
        },
        env_hint="configure stage",
    )
    assert advertised is not None
    assert advertised.public_profile is not None
    _compose, _nginx, env_file = render_service_files(
        _env(github_app=advertised),
        "img:tag",
        _BINDING,
    )
    assert "YOKE_GITHUB_APP_CLIENT_ID=Iv23public" in env_file
    assert "YOKE_GITHUB_APP_SLUG=yoke-development" in env_file
    assert "YOKE_GITHUB_APP_ID=123456" in env_file
    assert "YOKE_GITHUB_APP_WEB_URL=https://github.com" in env_file


def test_hosted_public_profile_rejects_partial_or_foreign_identity():
    base = {
        "issuer": "123456",
        "api_url": "https://api.github.com",
        "private_key_secret_arn": _APP_CONFIG.private_key_secret_arn,
    }
    with pytest.raises(
        github_app_deployment.GitHubAppDeploymentConfigError,
        match="incomplete or invalid",
    ):
        github_app_deployment.github_app_config_from_environment_settings(
            {"github_app": {**base, "public": {"client_id": "Iv23partial"}}},
            env_hint="configure stage",
        )

    with pytest.raises(
        github_app_deployment.GitHubAppDeploymentConfigError,
        match="does not match issuer",
    ):
        github_app_deployment.github_app_config_from_environment_settings(
            {
                "github_app": {
                    **base,
                    "public": {
                        "client_id": "Iv23foreign",
                        "app_slug": "foreign-app",
                        "app_id": 999,
                        "web_url": "https://github.com",
                    },
                }
            },
            env_hint="configure stage",
        )
