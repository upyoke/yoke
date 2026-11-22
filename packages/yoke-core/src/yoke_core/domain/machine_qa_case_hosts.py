"""OS slots for a case that needs several Test Machines at once.

``method_config.test_machines`` lists at least two ``{"os": ...}`` slots,
exactly one marked ``"driver": true``. Case-level ``capability_tags`` apply
to every slot. Hosts are chosen per slot at admission; afterwards the case's
host set is the execution's leases bound to it.
"""

from collections.abc import Mapping
from typing import Any

from yoke_contracts.machine_config.test_machine import TEST_MACHINE_OSES

_SLOT_FORM = (
    'list method_config.test_machines as at least two OS slots with exactly '
    'one driver, such as [{"os":"linux"},{"os":"macos","driver":true}], and '
    "omit the singular method_config.os"
)


def normalize_config_machines(config: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Validate and normalize OS slots in place; ``()`` for a single-host case."""
    if "test_machines" not in config:
        return ()
    from yoke_core.domain.machine_qa_case_machine import MachineConstraintError

    raw = config["test_machines"]
    invalid = MachineConstraintError(f"test_machine_set_invalid: {_SLOT_FORM}")
    if not isinstance(raw, list) or len(raw) < 2 or "os" in config:
        raise invalid
    slots = []
    for slot in raw:
        if (
            not isinstance(slot, Mapping)
            or set(slot) - {"os", "driver"}
            or slot.get("os") not in TEST_MACHINE_OSES
            or slot.get("driver", True) is not True
        ):
            raise invalid
        slots.append({"os": slot["os"], **({"driver": True} if slot.get("driver") else {})})
    if sum(1 for slot in slots if slot.get("driver")) != 1:
        raise invalid
    config["test_machines"] = slots
    return tuple(slots)


def case_slots(case: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """The case's normalized OS slots, driver included; ``()`` without slots."""
    import json

    config = case.get("method_config") or {}
    if isinstance(config, str):
        config = json.loads(config)
    return normalize_config_machines(dict(config))


def driver_slot_os(case: Mapping[str, Any]) -> str | None:
    return next((slot["os"] for slot in case_slots(case) if slot.get("driver")), None)


def case_machines(conn: Any, execution: Mapping[str, Any], case: Mapping[str, Any]) -> tuple[str, ...]:
    """The hosts the execution's leases bind to this case: driver and companions."""
    from yoke_core.domain.qa_case_host_custody import bound_case_hosts

    return tuple(sorted(bound_case_hosts(conn, execution, case)))
