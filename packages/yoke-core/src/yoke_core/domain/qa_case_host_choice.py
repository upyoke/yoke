"""Which hosts a machine plan case continues on, or how its opener selects.

Only the case that opens a chain selects hosts: by OS slots, or by OS and
capability tags, or the operator's per-run ``--test-machine``. A queued
single-host opener keeps its sole required wait on resume. Every later
``inherit`` case continues on the hosts its chain holds: the opener's bound
leases for a slotted chain, the recorded host (``execution_machine``) for a
single-host chain. An inherit case whose custody is gone never picks a
host; it is recorded blocked and the next plan run restarts the chain from
its opener.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from yoke_contracts.qa_case_starting_state import INHERIT

from yoke_core.domain.qa_plan_case_chain import INHERITED_PREDECESSOR_NOT_PASSED


class InheritedCustodyLost(ValueError):
    """An inherit case's chain no longer holds the hosts its opener left."""

    def __init__(self, blocker: dict[str, Any]) -> None:
        super().__init__(f"{INHERITED_PREDECESSOR_NOT_PASSED}: {blocker['reason']}")
        self.blocker = blocker


def custody_lost(
    execution: Mapping[str, Any],
    case: Mapping[str, Any],
    ordinal: int,
    chain: Sequence[Mapping[str, Any]],
    lost: str,
) -> InheritedCustodyLost:
    previous = execution["roster"][ordinal - 1] if ordinal > 0 else chain[0]
    opener = chain[0].get("case_key")
    return InheritedCustodyLost(
        {
            "predecessor_requirement_id": int(previous["requirement_id"]),
            "predecessor_case_key": previous.get("case_key"),
            "reason": (
                f"case {case.get('case_key')!r} inherits the machine its chain "
                f"opener {opener!r} left, but {lost}; it was not run. Rerun the "
                f"plan: the chain restarts from {opener!r}, which selects its "
                "hosts again"
            ),
        }
    )


def _serves_chain(conn: Any, name: str, chain: Sequence[Mapping[str, Any]]) -> bool:
    """Whether a held host matches the chain's OS and capability tags."""
    from yoke_contracts.machine_config.test_machine import TestMachineCapabilityError

    from yoke_core.domain.machine_qa_case_platform import (
        matching_platform_hosts,
        require_host_tags,
    )
    from yoke_core.domain.machine_qa_host_rows import test_machine_rows

    rows = test_machine_rows(conn, test_machine=name)
    try:
        if not rows or not matching_platform_hosts(rows, chain):
            return False
        require_host_tags(rows[0].settings, chain)
    except TestMachineCapabilityError:
        return False
    return True


def case_host_choice(
    conn: Any,
    execution: dict[str, Any],
    case: dict[str, Any],
    chain: list[dict[str, Any]],
    *,
    ordinal: int,
    requested: str | None,
    primary: str | None,
) -> tuple[str | None, tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """The driver (None selects one), the full host set, and slot waits.

    Slot waits are non-empty only for a slotted opener that selects; the
    case queues them when its set cannot be taken.
    """
    from yoke_core.domain.machine_qa_case_hosts import case_slots
    from yoke_core.domain.machine_qa_case_machine import (
        MACHINE_CONSTRAINT_MISMATCH,
        resolve_case_machine,
    )
    from yoke_core.domain.qa_host_set_turns import execution_waits
    from yoke_core.domain.qa_plan_execution_reentry import admitted_case
    from yoke_core.domain.qa_resume_machine import (
        execution_host_set,
        execution_machine,
    )

    explicit = resolve_case_machine(case, requested)
    inherit = case.get("starting_state") == INHERIT
    continues = inherit or admitted_case(execution) == ordinal
    if case_slots(chain[0]):
        held = execution_host_set(conn, execution, chain[0] if inherit else case)
        if continues and held is not None:
            if explicit and explicit not in {held[0], *held[1]}:
                raise ValueError(
                    f"{MACHINE_CONSTRAINT_MISMATCH}: this case continues on "
                    f"{', '.join(sorted({held[0], *held[1]}))}; omit --test-machine"
                )
            return held[0], tuple(sorted({held[0], *held[1]})), ()
        if inherit:
            raise custody_lost(
                execution, case, ordinal, chain,
                "the execution no longer holds a lease on every host of its slots",
            )
        from yoke_core.domain.qa_host_slot_turns import select_slot_hosts

        return select_slot_hosts(conn, execution, case, chain)
    if inherit:
        recorded = execution_machine(conn, execution, case)
        if recorded is None:
            raise custody_lost(
                execution, case, ordinal, chain, "no host is recorded for its chain"
            )
        if explicit and explicit != recorded:
            raise ValueError(
                f"{MACHINE_CONSTRAINT_MISMATCH}: this inherit case continues on "
                f"{recorded!r}; rerun with --test-machine {recorded} or omit the run pin"
            )
        return recorded, (recorded,), ()
    if explicit:
        return explicit, (explicit,), ()
    if not continues and execution.get("cursor_ordinal") == ordinal:
        waits = execution_waits(conn, str(execution["id"]))
        if len(waits) == 1 and waits[0]["need_id"] is None:
            driver = str(waits[0]["test_machine"])
            return driver, (driver,), ()
    driver = execution_machine(conn, execution, case) if continues else None
    if driver is None and primary and _serves_chain(conn, primary, chain):
        # A new opener keeps a held host that already matches; never by name.
        driver = primary
    return driver, ((driver,) if driver else ()), ()


__all__ = ["InheritedCustodyLost", "case_host_choice", "custody_lost"]
