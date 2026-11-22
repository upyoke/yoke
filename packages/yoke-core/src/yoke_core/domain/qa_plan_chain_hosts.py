"""The host selector each machine case chain is admitted with.

Before admission a chain names no host: it carries its opener's OS slots,
or the one OS its host cases share. Once admitted, a chain's hosts are its
opener's bound leases (``qa_case_host_custody``).
"""

from yoke_contracts.qa_case_starting_state import declares_starting_state

from collections.abc import Mapping, Sequence
from typing import Any

from yoke_core.domain.machine_qa_case_hosts import case_slots, driver_slot_os
from yoke_core.domain.machine_qa_case_platform import required_platform
from yoke_core.domain.qa_plan_case_chain import ends_chain


def chain_host_groups(
    roster: Sequence[Mapping[str, Any]],
) -> dict[int, tuple[str | None, tuple[str, ...], int | None, str | None]]:
    """Map requirements to (driver slot OS, slot OSes, isolated chain id, OS).

    A slotted chain has its driver slot's OS and every slot's OS in order; a
    single-host chain has only the OS its host cases require.
    """
    groups = {}
    chain = []
    for ordinal, row in enumerate(roster):
        chain.append(row)
        if ends_chain(roster, ordinal):
            mission_tail = (
                row.get("runner_id") == "agent_mission" and declares_starting_state(row)
                and row.get("starting_state") == "inherit"
            )
            host_cases = [case for case in chain if declares_starting_state(case)]
            slots = tuple(slot["os"] for slot in case_slots(chain[0]))
            group = (
                driver_slot_os(chain[0]),
                slots,
                int(chain[0]["requirement_id"]) if mission_tail else None,
                required_platform(host_cases, allow_undeclared=True)
                if host_cases and not slots else None,
            )
            groups.update((int(case["requirement_id"]), group) for case in chain)
            chain = []
    return groups
