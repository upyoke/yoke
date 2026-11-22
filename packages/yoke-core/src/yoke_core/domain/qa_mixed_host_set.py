"""Select all hosts before any overlapping case walks can take custody."""

from typing import Any

from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    test_machine_capability_tags,
)
from yoke_contracts.qa_case_starting_state import declares_starting_state
from yoke_core.domain.machine_qa_case_hosts import case_machines, case_slots
from yoke_core.domain.machine_qa_case_machine import resolve_case_machine
from yoke_core.domain.machine_qa_case_platform import (
    matching_platform_hosts,
    required_host_tags,
)
from yoke_core.domain.qa_plan_case_chain import ends_chain


def mixed_mission_host_set(
    conn: Any, execution: dict, ordinal: int, requested: str | None
) -> tuple[str, tuple[str, ...], tuple[str, ...]] | None:
    """Pick a stable driver per chain when more than one host can be needed.

    Deterministic-only rosters can release between chains. In a mission
    roster captures remain open until the walkers return, so admit the union
    at one FIFO turn before letting any chain acquire a host. Returns the
    current chain's driver, the union, and the current chain's companions.
    A chain keeps the hosts its opener's leases are bound to; an unbound
    chain picks by OS, slots and tags, never by a stored name.
    """
    from yoke_core.domain.qa_plan_chain_hosts import chain_host_groups

    roster = execution["roster"]
    if not any(
        case.get("runner_id") == "agent_mission" and declares_starting_state(case)
        for case in roster
    ):
        return None

    groups = chain_host_groups(roster)
    chains = []
    start = 0
    for index in range(len(roster)):
        if ends_chain(roster, index):
            chain = roster[start:index + 1]
            if declares_starting_state(chain[0]):
                chains.append((start, index, chain))
            start = index + 1
    selectors = {
        (groups[chain[0]["requirement_id"]], frozenset(required_host_tags(chain)))
        for _, _, chain in chains
    }
    if len(selectors) < 2:
        return None

    from yoke_core.domain.machine_qa_host_rows import test_machine_rows
    from yoke_core.domain.qa_case_host_custody import case_host_lease_id
    from yoke_core.domain.coordination_claims import get_claim
    from yoke_core.domain.qa_plan_host_leases import held_hosts

    held = held_hosts(conn, execution)
    rows = sorted(test_machine_rows(conn), key=lambda row: (row.test_machine not in held, row.test_machine))
    leases: set[str] = set()
    driver = None
    companions: tuple[str, ...] = ()
    for start, end, chain in chains:
        head = chain[0]
        current = start <= ordinal <= end
        explicit = resolve_case_machine(head, requested if current else None)
        bound = case_host_lease_id(conn, execution, head)
        if bound is not None and not explicit:
            explicit = get_claim(conn, bound).target.test_machine
        candidates = matching_platform_hosts(
            [row for row in rows if row.test_machine == explicit or not explicit],
            tuple(chain),
        )
        tags = required_host_tags(chain)
        eligible = [
            row for row in candidates
            if tags.issubset(test_machine_capability_tags(row.settings))
        ]
        if not eligible:
            raise TestMachineCapabilityError(
                f"test_machine_capability_tags_unavailable: QA requires {', '.join(sorted(tags))}; "
                "verify a matching Test Machine and retry with its name"
            )
        if not explicit:
            eligible = [row for row in eligible if row.verified_at is not None]
            if not eligible:
                raise TestMachineCapabilityError(
                    "test_machine_no_verified_host: verify a matching Test Machine before retrying QA"
                )
        selected = eligible[0].test_machine
        hosts = {selected, *case_machines(conn, execution, head)}
        if case_slots(head) and len(hosts) < len(case_slots(head)):
            from yoke_core.domain.qa_host_slot_turns import (
                pick_slot_hosts,
                slot_eligibility,
            )

            slots = slot_eligibility(conn, head, chain)
            others = [row.test_machine for row in rows if row.test_machine != selected]
            driver_index = next(
                i for i, slot in enumerate(case_slots(head)) if slot.get("driver")
            )
            rest = slots[:driver_index] + slots[driver_index + 1:]
            hosts = {selected, *(pick_slot_hosts(rest, others) or ())}
        leases.update(hosts)
        if current:
            driver, companions = selected, tuple(sorted(hosts - {selected}))
    return (driver, tuple(sorted(leases)), companions) if driver else None
