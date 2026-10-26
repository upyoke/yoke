"""The steering report's waiting-chains section.

The Frontier's dependency model (``ui/static/frontier_dependency_model.js``)
shows which items hold work up, how much each unblocks, and how many steps
behind its dependents sit. A chain can sit for days without anyone opening
that page, so the report reads the same live blocking edges
(:func:`live_blocking_edges`) and prints the chains compactly:

* a *head* is a blocker that waits on nothing live itself; it prints with how
  many items it unblocks, directly or down the chain, and the chain's depth,
  when it holds more than one item;
* an *unstarted link* is a blocker still before its implementation segment,
  with no live work claim, while work downstream of it is already in progress.
  Nothing moves until someone starts it and nobody is, so it prints flagged
  whether it is a head or sits mid-chain.

Loops are the deadlock section's and are skipped here. Each row names the
edges it holds, with gate and id, so a seat can narrow an edge heavier than
the work needs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Optional, Set

from yoke_core.domain import db_backend
from yoke_core.domain.dependency_cycles_read import LiveEdge, cycles_in
from yoke_core.domain.item_ref_resolution import internal_ids_for_refs
from yoke_core.domain.steering_fleet_report_render_text import SECTION_LIMIT, capped
from yoke_core.domain.work_claim_target_sql import scope_int_sql

HEADING = (
    "waiting chains — blockers holding the most work; ! marks an unstarted, "
    "unstaffed blocker with work behind it in progress"
)
_SHOWN = 3


@dataclass(frozen=True)
class HeldEdge:
    """One edge a chain row's blocker holds directly."""

    dependent: str
    gate_point: str
    satisfaction: str
    dependency_id: int

    def describe(self) -> str:
        return f"{self.dependent} ({self.gate_point} {self.satisfaction} #{self.dependency_id})"


@dataclass(frozen=True)
class WaitingChain:
    """One blocker and the work waiting behind it."""

    blocker: str
    stage: Optional[str]
    staffed: bool
    unblocks: int
    depth: int
    holds: tuple[HeldEdge, ...]
    waits_on: tuple[str, ...] = ()
    #: Downstream items already in progress, set only on an unstarted link.
    in_progress: tuple[str, ...] = ()
    #: Every item waiting behind the blocker, directly or down the chain.
    behind: tuple[str, ...] = ()
    #: Internal ids of the blocker and everything behind it, for seat scoping.
    member_ids: frozenset[int] = frozenset()

    @property
    def unstarted(self) -> bool:
        return bool(self.in_progress)

    def describe(self) -> str:
        staffing = "staffed" if self.staffed else "unstaffed"
        line = f"{self.blocker} ({self.stage or 'unresolved'}, {staffing})"
        if self.unstarted:
            line = f"! {line} unstarted while {_listed(self.in_progress)} in progress;"
        line += f" unblocks {self.unblocks}, {self.depth} deep"
        line += f"; holds {_listed([e.describe() for e in self.holds])}"
        if self.waits_on:
            line += f"; waits on {_listed(self.waits_on)}"
        return line

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocker": self.blocker,
            "stage": self.stage,
            "staffed": self.staffed,
            "unstarted": self.unstarted,
            "unblocks": self.unblocks,
            "depth": self.depth,
            "holds": [
                {
                    "dependent": e.dependent,
                    "gate_point": e.gate_point,
                    "satisfaction": e.satisfaction,
                    "dependency_id": e.dependency_id,
                }
                for e in self.holds
            ],
            "waits_on": list(self.waits_on),
            "in_progress": list(self.in_progress),
        }


def _listed(values: Iterable[str]) -> str:
    values = list(values)
    shown = ", ".join(values[:_SHOWN])
    return shown if len(values) <= _SHOWN else f"{shown} +{len(values) - _SHOWN}"


def chains_in(live: Iterable[LiveEdge], staffed: Set[str]) -> list[WaitingChain]:
    """Heads holding more than one item, and every unstarted link, ranked.

    ``staffed`` is the refs with a live work claim. An item counts as in
    progress when it is past its workflow's implementation entry or staffed.
    """
    live = list(live)
    looped = {ref for cycle in cycles_in(live) for ref in cycle.items}
    edges = [e for e in live if e.dependent_ref not in looped]
    edges = [e for e in edges if e.detail.blocking_item not in looped]
    facts: dict[str, Optional[dict[str, Any]]] = {}
    below: dict[str, list[LiveEdge]] = {}
    above: dict[str, list[str]] = {}
    for e in edges:
        facts[e.dependent_ref] = e.dependent
        facts.setdefault(e.detail.blocking_item, e.blocker)
        below.setdefault(e.detail.blocking_item, []).append(e)
        above.setdefault(e.dependent_ref, []).append(e.detail.blocking_item)

    def behind(ref: str) -> list[str]:
        seen: list[str] = []
        stack = [ref]
        while stack:
            for e in below.get(stack.pop(), []):
                if e.dependent_ref not in seen and e.dependent_ref != ref:
                    seen.append(e.dependent_ref)
                    stack.append(e.dependent_ref)
        return seen

    depths: dict[str, int] = {}

    def depth(ref: str) -> int:
        if ref not in depths:
            depths[ref] = 0  # A ref met again mid-walk ends it.
            depths[ref] = max(
                (1 + depth(e.dependent_ref) for e in below.get(ref, [])), default=0
            )
        return depths[ref]

    def started(ref: str) -> bool:
        fact = facts.get(ref)
        return ref in staffed or (fact is not None and not fact["unstarted"])

    rows = []
    for ref in sorted(below):
        downstream = behind(ref)
        fact = facts.get(ref)
        unstarted = fact is not None and fact["unstarted"] and ref not in staffed
        in_progress = tuple(r for r in downstream if started(r)) if unstarted else ()
        if not in_progress and (ref in above or len(downstream) < 2):
            continue
        rows.append(
            WaitingChain(
                blocker=ref,
                stage=fact["status"] if fact else None,
                staffed=ref in staffed,
                unblocks=len(downstream),
                depth=depth(ref),
                holds=tuple(
                    HeldEdge(
                        e.dependent_ref,
                        e.detail.gate_point,
                        e.detail.satisfaction,
                        int(e.detail.dependency_id),
                    )
                    for e in below[ref]
                ),
                waits_on=tuple(sorted(above.get(ref, ()))),
                in_progress=in_progress,
                behind=tuple(downstream),
            )
        )
    rows.sort(key=lambda c: (not c.unstarted, -c.unblocks, -c.depth, c.blocker))
    return rows


def _staffed_ids(conn: Any, ids: Iterable[int]) -> Set[int]:
    """Items among ``ids`` with an unreleased work claim held by a live session."""
    ids = sorted(set(ids))
    if not ids:
        return set()
    item_id = scope_int_sql(conn, "wc.scope", "item_id")
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        f"SELECT DISTINCT {item_id} AS item_id FROM work_claims wc "
        "JOIN harness_sessions hs ON hs.session_id = wc.session_id "
        "WHERE wc.released_at IS NULL AND wc.target_kind = 'item' "
        "AND hs.ended_at IS NULL AND hs.terminated_at IS NULL "
        f"AND {item_id} IN ({', '.join(marker for _ in ids)})",
        tuple(ids),
    ).fetchall()
    return {int(dict(row)["item_id"]) for row in rows}


def waiting_chains(
    conn: Any, live: Iterable[LiveEdge], project_id: int
) -> tuple[WaitingChain, ...]:
    """The project's chains: rows whose blocker or waiting work is in it.

    A chain that crosses projects is one chain, so a row stays when any item
    in it belongs to the project.
    """
    live = list(live)
    refs = {e.dependent_ref for e in live} | {e.detail.blocking_item for e in live}
    ids = internal_ids_for_refs(conn, refs)
    staffed_ids = _staffed_ids(conn, ids.values())
    staffed = {ref for ref, value in ids.items() if value in staffed_ids}
    projects = {e.dependent_ref: e.dependent["project_id"] for e in live}
    projects.update(
        (e.detail.blocking_item, e.blocker["project_id"]) for e in live if e.blocker
    )
    kept = []
    for chain in chains_in(live, staffed):
        members = (chain.blocker, *chain.behind)
        if any(projects.get(ref) == int(project_id) for ref in members):
            member_ids = frozenset(ids[ref] for ref in members if ref in ids)
            kept.append(replace(chain, member_ids=member_ids))
    return tuple(kept)


def seat_chains(
    chains: Iterable[WaitingChain], members: Optional[Set[int]]
) -> tuple[WaitingChain, ...]:
    """Chains holding a narrowed seat's items; all of them for a project seat."""
    if members is None:
        return tuple(chains)
    return tuple(chain for chain in chains if chain.member_ids & members)


def waiting_chain_section(report: Any) -> list[str]:
    """The section, heading and recovery included; empty when there are none."""
    chains: tuple[WaitingChain, ...] = getattr(report, "waiting_chains", ())
    if not chains:
        return []
    lines = [f"  {chain.describe()}" for chain in chains[:SECTION_LIMIT]]
    return [f"{HEADING}:", *capped(lines, len(chains))]


def waiting_chain_fingerprint(report: Any) -> list[Any]:
    """Age-blind identity: which blockers print, and which are flagged."""
    return sorted(
        (chain.blocker, chain.unstarted)
        for chain in getattr(report, "waiting_chains", ())
    )


__all__ = [
    "HEADING",
    "HeldEdge",
    "WaitingChain",
    "chains_in",
    "seat_chains",
    "waiting_chain_fingerprint",
    "waiting_chain_section",
    "waiting_chains",
]
