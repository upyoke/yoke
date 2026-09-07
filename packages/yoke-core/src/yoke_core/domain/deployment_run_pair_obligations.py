"""Which coordinated partners must merge before a prepared run may continue.

A product change that breaks a consumer ships as a pair: the producer and the
consumer that adapts to it merge separately, and the release must not go out
until both have landed. Continuing on the producer's own merge deploys a
product whose consumer is still the old one — the release is owed to the LAST
merge in the pair, not the first.

That pairing is already expressed at runtime. An ``item_dependencies`` row
with ``gate_point='integration'`` and ``satisfaction='fact:merged'`` says
exactly "this item's delivery waits for that item's merge", it is evaluated
from the blocker's ``merged_at`` rather than from a status field, and
``cmd_validate_composition`` already refuses to compose a run whose member
carries an unsatisfied one. Nothing here invents a linkage; it reads that one.

Preparation is the only thing that needs a second reading of it. A run
prepared before the pair has landed is *expected* to carry unsatisfied
integration edges — that pending merge is the obligation the run exists to
remember. So preparation separates those edges out and records them, while
every other composition failure stays fatal, and continuation re-reads them
with no exemption at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.dependency_satisfaction import unsatisfied_dependency_pairs
from yoke_core.domain.item_ref_columns import render_column_item_ref


PAIR_GATE_POINT = "integration"
PAIR_SATISFACTION = "fact:merged"


@dataclass(frozen=True)
class PairObligation:
    """One coordinated partner whose merge a prepared run is waiting for."""

    dependent_item_id: int
    blocking_item_id: int
    blocking_ref: str
    reason: str

    def describe(self) -> str:
        return f"{self.blocking_ref} ({self.reason})"


def _pair_edges(conn: Any, pairs: list[tuple[int, int]]) -> set[tuple[int, int]]:
    """Return the subset of *pairs* joined by a pair-merge dependency edge."""
    if not pairs:
        return set()
    found: set[tuple[int, int]] = set()
    for dependent, blocker in pairs:
        row = conn.execute(
            "SELECT 1 FROM item_dependencies WHERE dependent_item_id=%s "
            "AND blocking_item_id=%s AND gate_point=%s AND satisfaction=%s",
            (int(dependent), int(blocker), PAIR_GATE_POINT, PAIR_SATISFACTION),
        ).fetchone()
        if row is not None:
            found.add((int(dependent), int(blocker)))
    return found


def split_pending_pair_merges(
    conn: Any,
    item_ids: list[int],
) -> tuple[list[PairObligation], list[tuple[int, int, Any]]]:
    """Split unsatisfied blockers into pending pair merges and real failures.

    The first list is what a prepared run legitimately waits for. The second
    is everything else, which stays fatal at every phase.
    """
    blocked = unsatisfied_dependency_pairs(
        conn,
        item_ids,
        co_scheduled_blocker_ids=item_ids,
    )
    if not blocked:
        return [], []
    pair_keys = _pair_edges(
        conn,
        [(dependent, blocker) for dependent, blocker, _ in blocked],
    )
    pending: list[PairObligation] = []
    fatal: list[tuple[int, int, Any]] = []
    for dependent, blocker, verdict in blocked:
        if (int(dependent), int(blocker)) in pair_keys:
            pending.append(
                PairObligation(
                    dependent_item_id=int(dependent),
                    blocking_item_id=int(blocker),
                    blocking_ref=render_column_item_ref(conn, blocker),
                    reason=str(verdict.reason),
                )
            )
        else:
            fatal.append((dependent, blocker, verdict))
    return pending, fatal


def run_item_ids(conn: Any, run_id: str) -> list[int]:
    """Return the item ids enrolled in *run_id*."""
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s "
        "ORDER BY item_id",
        (run_id,),
    ).fetchall()
    return [int(row["item_id"] if hasattr(row, "keys") else row[0]) for row in rows]


def prepared_runs_awaiting_item(conn: Any, item_id: int) -> list[str]:
    """Return prepared run ids whose completion this item's merge advances.

    An item advances a run when it is enrolled in it, and also when it is the
    blocker of a pair-merge edge held by one of its members — which is how a
    consumer merge in one project continues a producer's prepared release in
    another. Both readings come from rows that already exist.
    """
    rows = conn.execute(
        "SELECT DISTINCT dr.id FROM deployment_runs dr "
        "JOIN deployment_run_items dri ON dri.run_id = dr.id "
        "WHERE dr.status='created' AND ("
        "  dri.item_id=%s"
        "  OR EXISTS ("
        "    SELECT 1 FROM item_dependencies d "
        "    WHERE d.dependent_item_id = dri.item_id "
        "    AND d.blocking_item_id=%s AND d.gate_point=%s "
        "    AND d.satisfaction=%s"
        "  )"
        ") ORDER BY dr.id",
        (int(item_id), int(item_id), PAIR_GATE_POINT, PAIR_SATISFACTION),
    ).fetchall()
    return [str(row["id"] if hasattr(row, "keys") else row[0]) for row in rows]


__all__ = [
    "PAIR_GATE_POINT",
    "PAIR_SATISFACTION",
    "PairObligation",
    "prepared_runs_awaiting_item",
    "run_item_ids",
    "split_pending_pair_merges",
]
