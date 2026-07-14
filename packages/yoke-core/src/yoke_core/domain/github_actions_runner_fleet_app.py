"""Validated operator GitHub App identity for a dedicated runner fleet."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, field_validator
from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    validate_github_api_endpoint,
)
from yoke_core.domain.github_app_control_plane import (
    GitHubAppControlPlaneConfigError,
    validate_github_app_issuer,
)


class RunnerFleetGitHubAppSettings(BaseModel):
    """Operator App identity used only by the dedicated runner fleet."""

    model_config = ConfigDict(extra="forbid")

    issuer: str
    api_url: str
    private_key_secret_arn: str

    @field_validator("issuer")
    @classmethod
    def _valid_issuer(cls, value: str) -> str:
        try:
            return validate_github_app_issuer(value)
        except GitHubAppControlPlaneConfigError as exc:
            raise ValueError(
                "must be a GitHub App client id or numeric app id"
            ) from exc

    @field_validator("api_url")
    @classmethod
    def _valid_api_url(cls, value: str) -> str:
        try:
            return validate_github_api_endpoint(value).base_url
        except GitHubApiOriginError as exc:
            raise ValueError(
                f"must be a canonical GitHub API endpoint: {exc}"
            ) from exc

    @field_validator("private_key_secret_arn")
    @classmethod
    def _valid_private_key_secret_arn(cls, value: str) -> str:
        cleaned = value.strip()
        if re.fullmatch(
            r"arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:"
            r"[A-Za-z0-9/_+=.@-]+",
            cleaned,
        ) is None:
            raise ValueError("must be a complete AWS Secrets Manager ARN")
        return cleaned
