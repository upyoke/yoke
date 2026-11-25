"""Build stable admission units from the ordered QA roster."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Any

from yoke_contracts.qa_case_starting_state import declares_starting_state
from yoke_core.domain.machine_qa_case_hosts import case_slots
from yoke_core.domain.machine_qa_case_platform import case_platform
from yoke_core.domain.qa_plan_case_chain import ends_chain
from yoke_core.domain.qa_plan_execution_store import canonical
from yoke_core.domain.qa_plan_host_free_cases import is_host_free_case


@dataclass(frozen=True)
class Partition:
    key: str
    roster: list[dict[str, Any]]
    hosts: tuple[str, ...]
    kind: str
    predecessors: tuple[str, ...] = ()


def partition_key(roster: list[dict[str, Any]], *, standalone: bool = False) -> str:
    """Hash target and ordered case identity, never transient execution state."""
    identity = [
        [row["case_key"], row["baseline_position"]]
        if standalone
        else int(row["requirement_id"])
        for row in roster
    ]
    target = str(roster[0].get("execution_target_digest") or "")
    return hashlib.sha256(canonical([target, identity]).encode()).hexdigest()


def _case_kind(case: dict[str, Any], *, item_lane: bool) -> str:
    if declares_starting_state(case) or case["verdict_path"] != "automatic":
        return "walk"
    if item_lane and is_host_free_case(case):
        return "lane"
    return "automatic"


def _case_hosts(case: dict[str, Any]) -> tuple[str, ...]:
    slots = tuple(slot["os"] for slot in case_slots(case))
    if slots:
        return slots
    if declares_starting_state(case):
        platform = case_platform(case, allow_undeclared=True)
        if platform:
            return (platform,)
    return ()


def roster_partitions(
    roster: list[dict[str, Any]], *, standalone: bool = False, item_lane: bool = False
) -> list[Partition]:
    """Keep same-machine inheritance whole and resolve declared ordering."""
    partitions: list[Partition] = []
    chain: list[dict[str, Any]] = []
    for ordinal, case in enumerate(roster):
        chain.append(case)
        if ends_chain(roster, ordinal):
            key = partition_key(chain, standalone=standalone)
            hosts = tuple(dict.fromkeys(os for row in chain for os in _case_hosts(row)))
            kind = _case_kind(chain[0], item_lane=item_lane)
            partitions.append(Partition(key, chain, hosts, kind))
            chain = []
    by_case: dict[tuple, list[str]] = {}
    for part in partitions:
        for row in part.roster:
            by_case.setdefault((row.get("plan_id"), row["case_key"]), []).append(part.key)
    return [
        replace(
            part,
            predecessors=tuple(dict.fromkeys(
                key
                for row in part.roster
                for key in by_case.get((row.get("plan_id"), row.get("after_case_key")), ())
                if key != part.key
            )),
        )
        for part in partitions
    ]
