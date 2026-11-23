"""OS slots for a case that needs several Test Machines at once.

``method_config.test_machines`` lists at least two ``{"os": ...}`` slots,
exactly one marked ``"driver": true``. On a slotted case ``capability_tags``
maps a slot OS to its tags, such as ``{"macos":["macos:15"]}``, and applies to
every slot of that OS. Hosts are chosen per slot at admission; afterwards the
case's host set is the execution's leases bound to it.
"""

from collections.abc import Mapping
from typing import Any

from yoke_contracts.machine_config.test_machine import (
    TEST_MACHINE_OSES,
    TestMachineCapabilityError,
    normalize_test_machine_capability_tags,
)

_SLOT_FORM = (
    'list method_config.test_machines as at least two OS slots with exactly '
    'one driver, such as [{"os":"linux"},{"os":"macos","driver":true}], and '
    "omit the singular method_config.os; set capability_tags as an object "
    'from a slot OS to its tags, such as {"macos":["macos:15"]}'
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
    if "capability_tags" in config:
        raw_tags = config["capability_tags"]
        if not isinstance(raw_tags, Mapping) or set(raw_tags) - {s["os"] for s in slots}:
            raise invalid
        try:
            normalized = {
                os_name: list(normalize_test_machine_capability_tags(tags))
                for os_name, tags in raw_tags.items()
            }
        except TestMachineCapabilityError as exc:
            raise MachineConstraintError(str(exc)) from exc
        config["capability_tags"] = {k: v for k, v in normalized.items() if v}
    return tuple(slots)


def _normalized_case(
    case: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    import json

    raw = case.get("method_config") or {}
    config = dict(json.loads(raw) if isinstance(raw, str) else raw)
    return config, normalize_config_machines(config)


def case_slots(case: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """The case's normalized OS slots, driver included; ``()`` without slots."""
    return _normalized_case(case)[1]


def driver_slot_os(case: Mapping[str, Any]) -> str | None:
    return next((slot["os"] for slot in case_slots(case) if slot.get("driver")), None)


def slot_os_tags(case: Mapping[str, Any], os_name: str) -> set[str]:
    """The tags a slotted case requires of every slot of *os_name*."""
    config, slots = _normalized_case(case)
    return set(config.get("capability_tags", {}).get(os_name, ())) if slots else set()


def case_machines(conn: Any, execution: Mapping[str, Any], case: Mapping[str, Any]) -> tuple[str, ...]:
    """The hosts the execution's leases bind to this case: driver and companions."""
    from yoke_core.domain.qa_case_host_custody import bound_case_hosts

    return tuple(sorted(bound_case_hosts(conn, execution, case)))
