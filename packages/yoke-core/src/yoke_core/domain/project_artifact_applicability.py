"""DB-backed applicability policy for generic rendered project artifacts."""

from __future__ import annotations

from typing import Mapping

from yoke_contracts.project_artifacts import (
    PROJECT_ARTIFACT_DEFAULT_APPLICABILITY_REASON,
    PROJECT_ARTIFACT_POLICY_CAPABILITY,
    PROJECT_ARTIFACT_POLICY_SETTING,
)
from yoke_core.domain.project_renderer_settings import ProjectRendererSettings


class ProjectArtifactApplicabilityError(ValueError):
    """The configured artifact applicability policy is malformed."""


def project_artifact_applicability(
    settings: ProjectRendererSettings,
) -> tuple[bool, str]:
    """Return whether the generic artifact contract applies, plus why."""

    capability = settings.capabilities.get(PROJECT_ARTIFACT_POLICY_CAPABILITY, {})
    raw_policy = capability.get(PROJECT_ARTIFACT_POLICY_SETTING)
    if raw_policy is None:
        return True, PROJECT_ARTIFACT_DEFAULT_APPLICABILITY_REASON
    if not isinstance(raw_policy, Mapping):
        raise ProjectArtifactApplicabilityError(
            f"{PROJECT_ARTIFACT_POLICY_CAPABILITY}."
            f"{PROJECT_ARTIFACT_POLICY_SETTING} must be an object"
        )
    unknown = sorted(set(raw_policy) - {"enabled", "reason"})
    if unknown:
        raise ProjectArtifactApplicabilityError(
            f"{PROJECT_ARTIFACT_POLICY_CAPABILITY}."
            f"{PROJECT_ARTIFACT_POLICY_SETTING} contains unknown settings: "
            + ", ".join(unknown)
        )
    enabled = raw_policy.get("enabled")
    if not isinstance(enabled, bool):
        raise ProjectArtifactApplicabilityError(
            f"{PROJECT_ARTIFACT_POLICY_CAPABILITY}."
            f"{PROJECT_ARTIFACT_POLICY_SETTING}.enabled must be a boolean"
        )
    reason = raw_policy.get("reason")
    if reason is None and enabled:
        return True, PROJECT_ARTIFACT_DEFAULT_APPLICABILITY_REASON
    if not isinstance(reason, str) or not reason.strip():
        raise ProjectArtifactApplicabilityError(
            f"{PROJECT_ARTIFACT_POLICY_CAPABILITY}."
            f"{PROJECT_ARTIFACT_POLICY_SETTING}.reason must be a non-empty string"
        )
    return enabled, reason.strip()


__all__ = [
    "ProjectArtifactApplicabilityError",
    "project_artifact_applicability",
]
