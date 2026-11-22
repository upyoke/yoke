"""Test Machine selection rules for QA cases: by OS and tag, never by host name.

Test Machines of one kind are identical, so a case selects its host by
``method_config.os``, OS slots in ``method_config.test_machines`` and
``method_config.capability_tags``. Only an operator's per-run
``--test-machine`` names a host, and it is never stored on the case.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
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
TEST_MACHINE_NAME_FORBIDDEN = "test_machine_name_forbidden"
_NAME_FORBIDDEN_MESSAGE = (
    f"{TEST_MACHINE_NAME_FORBIDDEN}: Test Machines of one kind are identical; "
    "select by method_config.os and capability_tags, or list "
    "method_config.test_machines as OS slots such as "
    '[{"os":"linux"},{"os":"macos","driver":true}]'
)
_STORED_NAME_RECOVERY = (
    "; rewrite the case with `yoke qa plan edit PLAN_SLUG --project P` or "
    "`yoke qa plan-cases replace --project P --plan-id N --stdin`, then "
    "rematerialize its requirements"
)


class MachineConstraintError(ValueError):
    """A case or run pin cannot satisfy the Test Machine selection rules."""


def _names_host(config: Mapping[str, Any], kinds: Iterable[Any]) -> bool:
    return (
        "test_machine" in config
        or "test_machine_reason" in config
        or any(isinstance(slot, str) for slot in config.get("test_machines") or [])
        or any(str(kind).startswith("test-machine:") for kind in kinds)
    )


def refuse_host_names(config: Mapping[str, Any], kinds: Iterable[Any] = ()) -> None:
    """Refuse any case declaration that names a specific Test Machine."""
    if _names_host(config, kinds):
        raise MachineConstraintError(_NAME_FORBIDDEN_MESSAGE)


def refuse_stored_host_names(case: Mapping[str, Any]) -> None:
    """Refuse at begin a stored case that still names a Test Machine.

    Such a row was written before hosts were selected by OS; it never runs,
    locally or on a host, until its case is rewritten.
    """
    import json

    config = case.get("method_config") or {}
    if isinstance(config, str):
        config = json.loads(config)
    kinds: list[Any] = []
    for field in ("required_capability_kinds", "capability_requirements"):
        value = case.get(field) or []
        kinds.extend(json.loads(value) if isinstance(value, str) else value)
    if _names_host(config, kinds):
        key = case.get("case_key") or case.get("requirement_id") or "unknown"
        raise MachineConstraintError(
            f"{_NAME_FORBIDDEN_MESSAGE}; stored case {key!r} still names one"
            + _STORED_NAME_RECOVERY
        )


def normalize_config_machine(config_contract_id: str, config: dict) -> None:
    """Validate a case's host selection: OS slots and capability tags."""
    from yoke_core.domain.machine_qa_case_hosts import normalize_config_machines

    refuse_host_names(config)
    normalize_config_machines(config)
    if "capability_tags" in config:
        if config_contract_id not in MACHINE_CONFIG_CONTRACTS:
            raise MachineConstraintError(
                "method_config.capability_tags requires a Command or Machine QA case"
            )
        try:
            config["capability_tags"] = list(
                normalize_test_machine_capability_tags(config["capability_tags"])
            )
        except TestMachineCapabilityError as exc:
            raise MachineConstraintError(str(exc)) from exc
    if (config.get("os") or config.get("test_machines")) and (
        config_contract_id not in MACHINE_CONFIG_CONTRACTS
    ):
        raise MachineConstraintError(
            "method_config.os and test_machines require a Command or Machine QA "
            "case; choose a supported runner before declaring a Test Machine"
        )


def require_registered_machine(
    conn: Any,
    *,
    project_id: int,
    test_machine: str | None,
) -> None:
    """Refuse a run pin that does not name a universe Test Machine."""
    if test_machine is None:
        return
    rows = test_machine_rows(conn)
    if test_machine in {row.test_machine for row in rows}:
        return
    available = ", ".join(row.test_machine for row in rows) or "none"
    raise MachineConstraintError(
        f"run pin requires unregistered test machine {test_machine!r}; registered "
        f"machines: {available}. Pass a registered name or omit --test-machine."
    )


def materialized_capability_kinds(
    required: Any, config: Mapping[str, Any]
) -> tuple[str, ...]:
    """A case's immutable capability snapshot; host names are refused."""
    values = capability_kinds(required, subject="QA plan case")
    refuse_host_names(config, values)
    return tuple(values)


def resolve_case_machine(case: Mapping[str, Any], requested: str | None) -> str | None:
    """The operator's per-run pin for this case, if any; cases name no host."""
    del case
    return validate_test_machine_resource_name(requested) if requested else None


def resolve_plan_machine(
    conn: Any,
    requirements: Sequence[Mapping[str, Any]],
    requested: str | None,
) -> str | None:
    """Check a plan-run ``--test-machine`` against each host-using case."""
    from yoke_contracts.qa_case_starting_state import declares_starting_state

    from yoke_core.domain.machine_qa_case_platform import (
        matching_platform_hosts,
        require_host_tags,
    )

    pinned = resolve_case_machine({}, requested)
    if pinned is None:
        return None
    rows = [row for row in test_machine_rows(conn) if row.test_machine == pinned]
    if not rows:
        return pinned
    for case in requirements:
        if not declares_starting_state(case):
            continue
        key = str(case.get("case_key") or case.get("requirement_id") or "unknown")
        try:
            if not matching_platform_hosts(rows, (case,)):
                raise TestMachineCapabilityError("no matching OS")
            require_host_tags(rows[0].settings, (case,))
        except TestMachineCapabilityError as exc:
            raise MachineConstraintError(
                f"{MACHINE_CONSTRAINT_MISMATCH}: case {key!r} cannot run on "
                f"--test-machine {pinned!r} ({rows[0].settings['os']}): {exc}; "
                "pin a host with the case's method_config.os and "
                "capability_tags, or omit the run pin"
            ) from exc
    return pinned


__all__ = [
    "MACHINE_CONFIG_CONTRACTS",
    "MACHINE_CONSTRAINT_MISMATCH",
    "MachineConstraintError",
    "TEST_MACHINE_NAME_FORBIDDEN",
    "materialized_capability_kinds",
    "normalize_config_machine",
    "refuse_host_names",
    "refuse_stored_host_names",
    "require_registered_machine",
    "resolve_case_machine",
    "resolve_plan_machine",
]
