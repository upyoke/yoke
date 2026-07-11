"""Validated settings for the GitHub Actions runner fleet capability."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from yoke_contracts.github_actions_runner_fleet import (
    CAPABILITY_TYPE,
    DEFAULT_RUNNER_LABELS,
    DEFAULT_RUNS_ON_VARIABLE,
)
from yoke_contracts.github_app_tokens import GITHUB_CAPABILITY_TYPE


DEFAULT_PROVIDER = "aws-ec2"
DEFAULT_INSTANCE_TYPE = "m7g.2xlarge"
DEFAULT_ARCHITECTURE = "arm64"
DEFAULT_DESIRED_RUNNER_COUNT = 1
DEFAULT_MAX_RUNNER_COUNT = 1
DEFAULT_ROOT_VOLUME_GB = 200
DEFAULT_AWS_CAPABILITY = "aws-admin"
DEFAULT_START_MODE = "autoscaled"
DEFAULT_SHUTDOWN_MODE = "terminate"


class RunnerFleetSettingsError(ValueError):
    """Raised when runner-fleet capability settings are malformed."""


class RunnerFleetInstanceSettings(BaseModel):
    """EC2 sizing intent for a dedicated Actions runner host or pool."""

    instance_type: str = DEFAULT_INSTANCE_TYPE
    architecture: str = DEFAULT_ARCHITECTURE
    root_volume_gb: int = Field(DEFAULT_ROOT_VOLUME_GB, ge=100)

    @field_validator("instance_type", "architecture")
    @classmethod
    def _non_empty_string(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must be non-empty")
        return cleaned


class RunnerFleetLifecycleSettings(BaseModel):
    """Lifecycle intent for an operator- or automation-started runner fleet."""

    start_mode: str = DEFAULT_START_MODE
    idle_shutdown_minutes: int = Field(30, ge=1)
    ephemeral_runners: bool = True
    shutdown_mode: str = DEFAULT_SHUTDOWN_MODE

    @field_validator("start_mode")
    @classmethod
    def _known_start_mode(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned not in {"operator", "manual", "scheduled", "autoscaled"}:
            raise ValueError(
                "must be one of operator, manual, scheduled, autoscaled"
            )
        return cleaned

    @field_validator("shutdown_mode")
    @classmethod
    def _known_shutdown_mode(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned not in {"stop", "terminate"}:
            raise ValueError("must be one of stop, terminate")
        return cleaned


class RunnerFleetNetworkSettings(BaseModel):
    """Optional network destinations required by deployment workflows."""

    deployment_ssh_environments: List[str] = Field(default_factory=list)

    @field_validator("deployment_ssh_environments")
    @classmethod
    def _clean_deployment_ssh_environments(
        cls, environments: List[str],
    ) -> List[str]:
        cleaned: List[str] = []
        for environment in environments:
            value = str(environment).strip()
            if not value:
                raise ValueError("must contain only non-empty environment names")
            if value not in cleaned:
                cleaned.append(value)
        return cleaned


class RunnerFleetSettings(BaseModel):
    """Non-secret project capability settings for a CI runner fleet."""

    repo: Optional[str] = None
    runner_labels: List[str] = Field(
        default_factory=lambda: list(DEFAULT_RUNNER_LABELS)
    )
    variable_name: str = DEFAULT_RUNS_ON_VARIABLE
    routing_enabled: bool = False
    provider: str = DEFAULT_PROVIDER
    desired_runner_count: int = Field(DEFAULT_DESIRED_RUNNER_COUNT, ge=1)
    max_runner_count: int = Field(DEFAULT_MAX_RUNNER_COUNT, ge=1)
    github_capability: Optional[str] = None
    github_app_environment: Optional[str] = None
    aws_capability: str = DEFAULT_AWS_CAPABILITY
    instance: RunnerFleetInstanceSettings = Field(
        default_factory=RunnerFleetInstanceSettings
    )
    lifecycle: RunnerFleetLifecycleSettings = Field(
        default_factory=RunnerFleetLifecycleSettings
    )
    network: Optional[RunnerFleetNetworkSettings] = None

    @field_validator("repo")
    @classmethod
    def _repo_slug_or_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if "/" not in cleaned:
            raise ValueError("must be owner/name")
        return cleaned

    @field_validator("runner_labels")
    @classmethod
    def _clean_runner_labels(cls, labels: List[str]) -> List[str]:
        cleaned: List[str] = []
        for label in labels:
            value = str(label).strip()
            if value and value not in cleaned:
                cleaned.append(value)
        if not cleaned:
            raise ValueError("must contain at least one label")
        return cleaned

    @field_validator("provider", "aws_capability")
    @classmethod
    def _clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must be non-empty")
        return cleaned

    @field_validator("variable_name")
    @classmethod
    def _github_variable_name(cls, value: str) -> str:
        cleaned = value.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", cleaned) is None:
            raise ValueError(
                "must start with a letter or underscore and contain only "
                "letters, numbers, and underscores"
            )
        if cleaned.upper().startswith("GITHUB_"):
            raise ValueError("must not start with the reserved GITHUB_ prefix")
        return cleaned

    @field_validator("github_capability")
    @classmethod
    def _clean_github_capability(
        cls, value: Optional[str],
    ) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must be non-empty when provided")
        if cleaned != GITHUB_CAPABILITY_TYPE:
            raise ValueError(
                f"must be {GITHUB_CAPABILITY_TYPE!r}; runner fleets require "
                "the binding-owned GitHub capability"
            )
        return cleaned

    @field_validator("github_app_environment")
    @classmethod
    def _clean_github_app_environment(
        cls, value: Optional[str],
    ) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must be non-empty when provided")
        return cleaned

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        if value != DEFAULT_PROVIDER:
            raise ValueError(f"must be {DEFAULT_PROVIDER!r}")
        return value

    @model_validator(mode="after")
    def _max_covers_desired(self) -> "RunnerFleetSettings":
        if self.max_runner_count < self.desired_runner_count:
            raise ValueError(
                "max_runner_count must be greater than or equal to "
                "desired_runner_count"
            )
        if self.desired_runner_count != 1 or self.max_runner_count != 1:
            raise ValueError(
                "runner fleet v1 requires exactly one isolated runner host"
            )
        if not self.lifecycle.ephemeral_runners:
            raise ValueError("runner fleet v1 requires ephemeral_runners=true")
        return self


def default_settings(repo: Optional[str] = None) -> Dict[str, Any]:
    """Return the default non-secret settings document."""
    return RunnerFleetSettings(repo=repo).model_dump(exclude_none=True)


def canonical_json(settings: RunnerFleetSettings) -> str:
    """Render stable JSON for storage in ``project_capabilities.settings``."""
    return json.dumps(settings.model_dump(exclude_none=True), sort_keys=True)


def validate(raw: Dict[str, Any]) -> RunnerFleetSettings:
    """Validate and normalize a runner-fleet settings dictionary."""
    try:
        return RunnerFleetSettings.model_validate(raw)
    except ValueError as exc:
        raise RunnerFleetSettingsError(
            f"invalid {CAPABILITY_TYPE} capability settings: {exc}"
        ) from exc


def validate_json_string(raw_json: str) -> str:
    """Validate a JSON string and return canonical storage JSON."""
    try:
        parsed = json.loads(raw_json)
    except ValueError as exc:
        raise RunnerFleetSettingsError(
            f"invalid {CAPABILITY_TYPE} capability settings JSON: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise RunnerFleetSettingsError(
            f"invalid {CAPABILITY_TYPE} capability settings: root must be "
            "a JSON object"
        )
    return canonical_json(validate(parsed))


def load_json_string(raw_json: Optional[str]) -> RunnerFleetSettings:
    """Load stored settings, returning defaults when the row is absent."""
    if raw_json is None or not str(raw_json).strip():
        return RunnerFleetSettings()
    try:
        parsed = json.loads(raw_json)
    except ValueError as exc:
        raise RunnerFleetSettingsError(
            f"invalid stored {CAPABILITY_TYPE} capability settings JSON: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise RunnerFleetSettingsError(
            f"invalid stored {CAPABILITY_TYPE} capability settings: root "
            "must be a JSON object"
        )
    return validate(parsed)


__all__ = [
    "CAPABILITY_TYPE",
    "DEFAULT_ARCHITECTURE",
    "DEFAULT_AWS_CAPABILITY",
    "DEFAULT_DESIRED_RUNNER_COUNT",
    "DEFAULT_INSTANCE_TYPE",
    "DEFAULT_MAX_RUNNER_COUNT",
    "DEFAULT_PROVIDER",
    "DEFAULT_ROOT_VOLUME_GB",
    "DEFAULT_RUNNER_LABELS",
    "DEFAULT_RUNS_ON_VARIABLE",
    "DEFAULT_SHUTDOWN_MODE",
    "DEFAULT_START_MODE",
    "RunnerFleetNetworkSettings",
    "RunnerFleetSettings",
    "RunnerFleetSettingsError",
    "canonical_json",
    "default_settings",
    "load_json_string",
    "validate",
    "validate_json_string",
]
