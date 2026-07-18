"""Errors raised by project artifact reconciliation."""


class ProjectArtifactError(RuntimeError):
    """Artifact reconciliation cannot proceed safely."""


__all__ = ["ProjectArtifactError"]
