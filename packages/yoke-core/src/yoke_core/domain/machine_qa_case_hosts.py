"""Declared simultaneous Test Machines beside a case's driving machine."""

from collections.abc import Mapping
from typing import Any

from yoke_contracts.machine_config.test_machine import (
    validate_test_machine_resource_name,
)


def normalize_config_machines(config: dict[str, Any]) -> tuple[str, ...]:
    """Require an explicit driver and a unique, ordered set of companion hosts."""
    if "machines" not in config:
        return ()
    from yoke_core.domain.machine_qa_case_machine import MachineConstraintError

    raw = config["machines"]
    if not isinstance(raw, list) or len(raw) < 2 or not config.get("machine"):
        raise MachineConstraintError(
            "test_machine_set_invalid: method_config.machines requires at least two "
            "unique machine names and method_config.machine naming the driving host"
        )
    try:
        names = [validate_test_machine_resource_name(value) for value in raw]
    except (TypeError, ValueError) as exc:
        raise MachineConstraintError(
            "test_machine_set_invalid: use registered Test Machine names in method_config.machines"
        ) from exc
    if len(set(names)) != len(names) or config["machine"] not in names:
        raise MachineConstraintError(
            "test_machine_set_invalid: list every required host once, including method_config.machine"
        )
    config["machines"] = sorted(names)
    return tuple(config["machines"])


def case_machines(
    case: Mapping[str, Any], requested: str | None = None
) -> tuple[str, ...]:
    """The full host set a case must hold; the singular pin selects its driver."""
    from yoke_core.domain.machine_qa_case_machine import resolve_case_machine

    config = dict(case.get("method_config") or {})
    declared = normalize_config_machines(config)
    driver = resolve_case_machine(case, requested)
    return declared or ((driver,) if driver else ())
