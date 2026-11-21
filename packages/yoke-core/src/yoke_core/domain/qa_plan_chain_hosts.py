"""One driving host and complete custody set for each machine case chain."""

from yoke_contracts.qa_case_starting_state import needs_test_machine

from collections.abc import Mapping, Sequence
from typing import Any

from yoke_core.domain.machine_qa_case_hosts import case_machines
from yoke_core.domain.machine_qa_case_platform import required_platform
from yoke_core.domain.machine_qa_case_machine import resolve_case_machine
from yoke_core.domain.qa_plan_case_chain import ends_chain


def chain_host_groups(
    roster: Sequence[Mapping[str, Any]],
) -> dict[int, tuple[str | None, tuple[str, ...], int | None, str | None]]:
    """Map requirements to (driver, hosts, isolated chain id, unpinned OS)."""
    groups = {}
    chain = []
    hosts: set[str] = set()
    for ordinal, row in enumerate(roster):
        chain.append(row)
        hosts.update(case_machines(row))
        if ends_chain(roster, ordinal):
            mission_tail = (
                row.get("runner_id") == "agent_mission" and needs_test_machine(row)
                and row.get("starting_state") == "inherit"
            )
            host_cases = [case for case in chain if needs_test_machine(case)]
            group = (
                resolve_case_machine(chain[0], None),
                tuple(sorted(hosts)),
                int(chain[0]["requirement_id"]) if mission_tail else None,
                required_platform(host_cases, allow_undeclared=True)
                if host_cases and not hosts else None,
            )
            groups.update((int(case["requirement_id"]), group) for case in chain)
            chain = []
            hosts = set()
    return groups
