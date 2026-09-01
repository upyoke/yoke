"""Durable Test Machine constraints for materialized QA plan cases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from yoke_contracts.machine_config.test_machine import (
    is_test_machine_capability_type,
    test_machine_capability_type,
    test_machine_resource_name,
    validate_test_machine_resource_name,
)

from yoke_core.domain.machine_qa_capability_rows import (
    test_machine_capability_rows,
)
from yoke_core.domain.qa_method_capabilities import capability_kinds


MACHINE_CONFIG_CONTRACTS = frozenset(
    {
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
    """Validate and normalize an optional ``method_config.machine`` value."""
    if "machine" not in config:
        return None
    if config_contract_id not in MACHINE_CONFIG_CONTRACTS:
        raise MachineConstraintError(
            "method_config.machine is only valid for Machine QA cases"
        )
    try:
        machine = validate_test_machine_resource_name(config["machine"])
    except (TypeError, ValueError) as exc:
        raise MachineConstraintError(
            "method_config.machine must name a valid registered Test Machine"
        ) from exc
    config["machine"] = machine
    return machine


def require_registered_machine(
    conn: Any,
    *,
    project_id: int,
    machine: str | None,
    subject: str = "case",
) -> None:
    """Refuse a constraint that does not name its plan project's machine."""
    if machine is None:
        return
    rows = test_machine_capability_rows(conn, project_id=int(project_id))
    if machine in {row.machine for row in rows}:
        return
    available = ", ".join(row.machine for row in rows) or "none"
    if subject == "case":
        recovery = "Register it before saving the plan."
    elif subject == "run pin":
        recovery = "Pass a registered name or omit --machine."
    else:
        recovery = "Register it or update and rematerialize the plan."
    raise MachineConstraintError(
        f"{subject} requires unregistered test machine {machine!r}; registered "
        f"machines: {available}. {recovery}"
    )


def materialized_capability_kinds(
    required: Any, config: Mapping[str, Any]
) -> tuple[str, ...]:
    """Add a case's specific machine to its immutable capability snapshot."""
    values = list(capability_kinds(required, subject="QA plan case"))
    machine = config.get("machine")
    if machine is not None:
        specific = test_machine_capability_type(
            validate_test_machine_resource_name(machine)
        )
        if specific not in values:
            values.append(specific)
    return tuple(values)


def required_case_machine(required: Any) -> str | None:
    """Read at most one specific Test Machine from capability requirements."""
    machines = {
        test_machine_resource_name(kind)
        for kind in capability_kinds(required, subject="QA case")
        if is_test_machine_capability_type(kind)
    }
    if len(machines) > 1:
        raise MachineConstraintError("QA case declares multiple specific Test Machines")
    return next(iter(machines), None)


def resolve_case_machine(case: Mapping[str, Any], requested: str | None) -> str | None:
    """Apply case-constraint precedence and validate an optional run pin."""
    required = required_case_machine(case.get("required_capability_kinds"))
    pinned = validate_test_machine_resource_name(requested) if requested else None
    if required and pinned and required != pinned:
        key = str(case.get("case_key") or case.get("requirement_id") or "unknown")
        raise MachineConstraintError(
            f"{MACHINE_CONSTRAINT_MISMATCH}: case {key!r} requires {required!r}, "
            f"but --machine named {pinned!r}; rerun with --machine {required} or "
            "omit the run pin"
        )
    return required or pinned


def resolve_plan_machine(
    requirements: Sequence[Mapping[str, Any]],
    requested: str | None,
) -> str | None:
    """Resolve the one machine usable by an uninterrupted plan lease."""
    constrained = {
        machine
        for row in requirements
        if (machine := required_case_machine(row.get("required_capability_kinds")))
    }
    if len(constrained) > 1:
        names = ", ".join(sorted(constrained))
        raise MachineConstraintError(
            "test_machine_plan_constraints_conflict: one plan execution holds "
            f"one uninterrupted machine lease, but its cases require {names}; "
            "split those cases into one plan per machine"
        )
    plan_machine = next(iter(constrained), None)
    return resolve_case_machine(
        {
            "case_key": "plan roster",
            "required_capability_kinds": (
                [test_machine_capability_type(plan_machine)] if plan_machine else []
            ),
        },
        requested,
    )


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
