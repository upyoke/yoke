"""Closed registry validation for Machine QA fixture operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from yoke_core.domain.machine_qa_fixture_validation_common import (
    MAX_FIXTURE_OPERATIONS,
    MachineQaFixtureOperationError,
    Validator,
)
from yoke_core.domain.machine_qa_fixture_validation_machine import (
    MACHINE_SETUP_VALIDATORS,
)
from yoke_core.domain.machine_qa_fixture_validation_repository import (
    POST_VALIDATORS,
    REPOSITORY_SETUP_VALIDATORS,
)
from yoke_core.domain.machine_qa_recipe_contracts import (
    REGISTERED_POST_STATE_ASSERTION_IDS,
    REGISTERED_SETUP_OPERATION_IDS,
)


SETUP_VALIDATORS: dict[str, Validator] = {
    **MACHINE_SETUP_VALIDATORS,
    **REPOSITORY_SETUP_VALIDATORS,
}
if frozenset(SETUP_VALIDATORS) != REGISTERED_SETUP_OPERATION_IDS:
    raise RuntimeError("fixture executor setup registry drifted")
if frozenset(POST_VALIDATORS) != REGISTERED_POST_STATE_ASSERTION_IDS:
    raise RuntimeError("fixture executor assertion registry drifted")


def _validate_operations(
    operations: Sequence[Mapping[str, Any]],
    *,
    validators: Mapping[str, Validator],
    field: str,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    if (
        isinstance(operations, (str, bytes))
        or not isinstance(operations, Sequence)
        or len(operations) > MAX_FIXTURE_OPERATIONS
    ):
        raise MachineQaFixtureOperationError(f"{field} must be a bounded sequence")
    normalized = []
    for operation in operations:
        if (
            not isinstance(operation, Mapping)
            or set(operation) != {"id", "parameters"}
            or not isinstance(operation.get("id"), str)
            or not isinstance(operation.get("parameters"), Mapping)
        ):
            raise MachineQaFixtureOperationError(
                f"{field} entries require exactly id and parameters"
            )
        operation_id = operation["id"]
        validator = validators.get(operation_id)
        if validator is None:
            raise MachineQaFixtureOperationError(
                f"{field} names an unregistered operation"
            )
        normalized.append(
            (
                operation_id,
                validator(operation["parameters"]),
            )
        )
    return tuple(normalized)


def validate_setup_operations(
    operations: Sequence[Mapping[str, Any]],
) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Validate a complete setup batch before any remote mutation."""
    return _validate_operations(
        operations,
        validators=SETUP_VALIDATORS,
        field="setup_operations",
    )


def validate_post_state_assertions(
    operations: Sequence[Mapping[str, Any]],
) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Validate a complete post-state batch before any remote call."""
    return _validate_operations(
        operations,
        validators=POST_VALIDATORS,
        field="post_state_assertions",
    )


__all__ = [
    "MAX_FIXTURE_OPERATIONS",
    "MachineQaFixtureOperationError",
    "validate_post_state_assertions",
    "validate_setup_operations",
]
