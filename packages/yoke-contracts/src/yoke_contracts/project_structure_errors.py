"""Shared errors for Project Structure payload validation and operations."""


class ProjectStructureError(Exception):
    """Base class for Project Structure domain errors."""


class UsageError(ProjectStructureError):
    """CLI argument or op-shape misuse."""


class ValidationError(ProjectStructureError):
    """Envelope or payload validation failure."""
