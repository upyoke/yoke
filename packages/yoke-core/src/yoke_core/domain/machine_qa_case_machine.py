"""Durable Test Machine constraints for materialized QA plan cases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    normalize_test_machine_capability_tags,
    validate_test_machine_resource_name,
)

from yoke_core.domain.machine_qa_host_rows import (
    test_machine_rows,
)
from yoke_core.domain.qa_method_capabilities import capability_kinds


_MACHINE_REQUIREMENT_PREFIX = "test-machine:"


def test_machine_requirement_kind(name: str) -> str:
    return _MACHINE_REQUIREMENT_PREFIX + validate_test_machine_resource_name(name)


def requirement_machine_name(kind: str) -> str | None:
    if kind.startswith(_MACHINE_REQUIREMENT_PREFIX):
        return validate_test_machine_resource_name(kind[len(_MACHINE_REQUIREMENT_PREFIX):])
    return None


MACHINE_CONFIG_CONTRACTS = frozenset(
    {
        "command",
        "agent-mission",
        "machine-state-check",
        "terminal-check",
        "terminal-inspection",
    }
)
MACHINE_CONSTRAINT_MISMATCH = "test_machine_constraint_mismatch"


class MachineConstraintError(ValueError):
    """A run pin or plan roster cannot satisfy a case machine constraint."""


def normalize_config_machine(config_contract_id: str, config: dict) -> str | None:
    """Validate and normalize an optional ``method_config.test_machine`` value."""
    from yoke_core.domain.machine_qa_case_hosts import normalize_config_machines

    normalize_config_machines(config)
    if "capability_tags" in config:
        if config_contract_id not in MACHINE_CONFIG_CONTRACTS or (
            config_contract_id == "command" and not config.get("test_machine")
        ):
            raise MachineConstraintError(
                "method_config.capability_tags requires a Machine QA case"
            )
        try:
            config["capability_tags"] = list(
                normalize_test_machine_capability_tags(config["capability_tags"])
            )
        except TestMachineCapabilityError as exc:
            raise MachineConstraintError(str(exc)) from exc
    if "test_machine_reason" in config:
        reason = config["test_machine_reason"]
        if not config.get("test_machine") or not isinstance(reason, str) or not reason.strip():
            raise MachineConstraintError(
                "method_config.test_machine_reason must state why the case requires "
                "the named test_machine; use method_config.os for any host of that type"
            )
        config["test_machine_reason"] = reason.strip()
    if "test_machine" not in config:
        return None
    if config_contract_id not in MACHINE_CONFIG_CONTRACTS:
        raise MachineConstraintError(
            "method_config.test_machine requires a Command or Machine QA case; "
            "choose a supported local runner before declaring a Test Machine"
        )
    try:
        test_machine = validate_test_machine_resource_name(config["test_machine"])
    except (TypeError, ValueError) as exc:
        raise MachineConstraintError(
            "method_config.test_machine must name a valid registered Test Machine"
        ) from exc
    config["test_machine"] = test_machine
    return test_machine


def require_registered_machine(
    conn: Any,
    *,
    project_id: int,
    test_machine: str | None,
    subject: str = "case",
) -> None:
    """Refuse a constraint that does not name a universe Test Machine."""
    if test_machine is None:
        return
    rows = test_machine_rows(conn)
    if test_machine in {row.test_machine for row in rows}:
        return
    available = ", ".join(row.test_machine for row in rows) or "none"
    if subject == "case":
        recovery = "Register it before saving the plan."
    elif subject == "run pin":
        recovery = "Pass a registered name or omit --test-machine."
    else:
        recovery = "Register it or update and rematerialize the plan."
    raise MachineConstraintError(
        f"{subject} requires unregistered test machine {test_machine!r}; registered "
        f"machines: {available}. {recovery}"
    )


def materialized_capability_kinds(
    required: Any, config: Mapping[str, Any]
) -> tuple[str, ...]:
    """Add a case's specific machine to its immutable capability snapshot."""
    values = list(capability_kinds(required, subject="QA plan case"))
    test_machine = config.get("test_machine")
    if test_machine is not None:
        specific = test_machine_requirement_kind(test_machine)
        if specific not in values:
            values.append(specific)
    return tuple(values)


def required_case_machine(required: Any) -> str | None:
    """Read at most one specific Test Machine from capability requirements."""
    machines = {
        machine
        for kind in capability_kinds(required, subject="QA case")
        if (machine := requirement_machine_name(kind)) is not None
    }
    if len(machines) > 1:
        raise MachineConstraintError("QA case declares multiple specific Test Machines")
    return next(iter(machines), None)


def resolve_case_machine(case: Mapping[str, Any], requested: str | None) -> str | None:
    """Apply case-constraint precedence and validate an optional run pin."""
    required = required_case_machine(
        materialized_capability_kinds(
            case.get("required_capability_kinds"), case.get("method_config") or {}
        )
    )
    pinned = validate_test_machine_resource_name(requested) if requested else None
    if required and pinned and required != pinned:
        key = str(case.get("case_key") or case.get("requirement_id") or "unknown")
        raise MachineConstraintError(
            f"{MACHINE_CONSTRAINT_MISMATCH}: case {key!r} requires {required!r}, "
            f"but --test-machine named {pinned!r}; rerun with --test-machine {required} or "
            "omit the run pin"
        )
    return required or pinned


def resolve_plan_machine(
    requirements: Sequence[Mapping[str, Any]],
    requested: str | None,
) -> str | None:
    """Validate an explicit global pin; otherwise schedule each case's host."""
    for row in requirements:
        resolve_case_machine(row, requested)
    return validate_test_machine_resource_name(requested) if requested else None


__all__ = [
    "MACHINE_CONFIG_CONTRACTS",
    "MACHINE_CONSTRAINT_MISMATCH",
    "MachineConstraintError",
    "materialized_capability_kinds",
    "normalize_config_machine",
    "require_registered_machine",
    "required_case_machine",
    "resolve_case_machine",
    "resolve_plan_machine",
]
