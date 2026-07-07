"""Shared constants for GitHub Actions runner-fleet routing."""

CAPABILITY_TYPE = "github-actions-runner-fleet"
DEFAULT_RUNNER_LABELS = (
    "self-hosted", "Linux", "ARM64", "yoke-github-actions",
)
DEFAULT_RUNS_ON_VARIABLE = "YOKE_LINUX_RUNS_ON"

__all__ = [
    "CAPABILITY_TYPE",
    "DEFAULT_RUNNER_LABELS",
    "DEFAULT_RUNS_ON_VARIABLE",
]
