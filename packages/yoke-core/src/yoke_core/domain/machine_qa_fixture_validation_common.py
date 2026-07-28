"""Shared validation primitives for Machine QA fixture operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable


MAX_FIXTURE_OPERATIONS = 50
Validator = Callable[[Mapping[str, Any]], dict[str, Any]]


class MachineQaFixtureOperationError(ValueError):
    """A fixture operation is outside the closed execution contract."""


def operation_error(
    operation_id: str,
    reason: str,
) -> MachineQaFixtureOperationError:
    """Build a consistently scoped fixture validation error."""
    return MachineQaFixtureOperationError(f"{operation_id}: {reason}")


def exact_keys(
    operation_id: str,
    parameters: Mapping[str, Any],
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    """Require exactly the registered required and optional fields."""
    optional_fields = set(optional or ())
    allowed = required | optional_fields
    if set(parameters) == required | (set(parameters) & optional_fields):
        return
    missing = sorted(required - set(parameters))
    unknown = sorted(set(parameters) - allowed)
    details = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if unknown:
        details.append("unknown " + ", ".join(unknown))
    raise operation_error(
        operation_id,
        "; ".join(details) or "invalid fields",
    )


def bounded_text(
    operation_id: str,
    parameters: Mapping[str, Any],
    field: str,
    *,
    max_length: int = 1000,
) -> str:
    """Read required, non-empty bounded text."""
    raw = parameters.get(field)
    if not isinstance(raw, str) or not raw or len(raw) > max_length:
        raise operation_error(operation_id, f"{field} must be bounded text")
    return raw


def bounded_integer(
    operation_id: str,
    parameters: Mapping[str, Any],
    field: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    """Read a required integer inside the registered range."""
    raw = parameters.get(field)
    if (
        not isinstance(raw, int)
        or isinstance(raw, bool)
        or not minimum <= raw <= maximum
    ):
        raise operation_error(
            operation_id,
            f"{field} is outside its registered range",
        )
    return raw


def boolean(
    operation_id: str,
    parameters: Mapping[str, Any],
    field: str,
) -> bool:
    """Read a required boolean."""
    raw = parameters.get(field)
    if not isinstance(raw, bool):
        raise operation_error(operation_id, f"{field} must be boolean")
    return raw


def exact_value(
    operation_id: str,
    parameters: Mapping[str, Any],
    field: str,
    expected: Any,
) -> Any:
    """Require a field to equal its closed registered value."""
    if parameters.get(field) != expected:
        raise operation_error(operation_id, f"{field} is not registered")
    return expected


__all__ = [
    "MAX_FIXTURE_OPERATIONS",
    "MachineQaFixtureOperationError",
    "Validator",
    "boolean",
    "bounded_integer",
    "bounded_text",
    "exact_keys",
    "exact_value",
    "operation_error",
]
