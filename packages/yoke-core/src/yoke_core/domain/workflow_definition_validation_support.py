"""Shared typed validation helpers for workflow-definition modules."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


class WorkflowDefinitionError(ValueError):
    """A definition cannot be published because its data is invalid."""


def require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkflowDefinitionError(f"{path} must be an object")
    return value


def require_sequence(value: Any, path: str) -> Sequence[Any]:
    if not isinstance(value, (list, tuple)):
        raise WorkflowDefinitionError(f"{path} must be an array")
    return value


def require_exact_keys(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    path: str,
) -> None:
    extra = set(value) - allowed
    if extra:
        raise WorkflowDefinitionError(
            f"{path} has unknown keys: {sorted(extra)}"
        )


def require_nonempty_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowDefinitionError(f"{path} must be non-empty text")
    return value.strip()


__all__ = [
    "WorkflowDefinitionError",
    "require_exact_keys",
    "require_mapping",
    "require_nonempty_text",
    "require_sequence",
]
