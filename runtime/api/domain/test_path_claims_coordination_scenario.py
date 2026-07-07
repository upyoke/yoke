"""End-to-end coverage for the coordination_only no-mutex contract.

Three items mutually linked by ``coordination_only`` ``item_dependencies``
edges and registering path claims on a single shared target now activate
in parallel — no path-claim serialisation, no mutex lane.

The contract being pinned: ``coordination_only`` is the operator's
explicit declaration that the two items touch overlapping files but no
lifecycle ordering is required. The overlap classifier returns
``OverlapClassification.NONE`` for any candidate / blocker pair whose
only inter-item dep edge is ``coordination_only``, so every candidate
registers as ``state='planned'`` and activates independently. Any
same-hunk conflict surfaces as a normal git merge conflict at PR-merge
time and is resolved by :mod:`yoke_core.engines.merge_worktree`.

Item ids are pytest-local integers per the AGENTS.md ``## Testing``
rule. No literal YOK-N token appears in this file.
"""

from __future__ import annotations

import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    local_human,
    seed_target,
)
from yoke_core.domain.dependency_planning import evaluate_batch_gates
from yoke_core.domain.path_claims import get_claim
from yoke_core.domain.path_claims_register import register_for_item


SHARED_PATH = "runtime/api/domain"
COORD_RATIONALE = (
    "Three items each amend disjoint regions of the shared module; "
    "coordination_only edge declares no lifecycle ordering required."
)


def _seed_item(conn, *, item_id: int) -> int:
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()
    return item_id


_DEP_DDL = (
    "CREATE TABLE IF NOT EXISTS item_dependencies ("
    "id INTEGER PRIMARY KEY, dependent_item TEXT NOT NULL, "
    "blocking_item TEXT NOT NULL, "
    "gate_point TEXT NOT NULL DEFAULT 'activation', "
    "satisfaction TEXT NOT NULL DEFAULT 'status:done', "
    "source TEXT NOT NULL, session_id INTEGER, "
    "rationale TEXT NOT NULL DEFAULT '', "
    "evidence_json TEXT NOT NULL DEFAULT '{}', "
    "created_at TEXT NOT NULL)"
)


def _add_coord_edge(conn, *, dependent: int, blocking: int):
    conn.execute(_DEP_DDL)
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item, blocking_item, "
        "gate_point, satisfaction, source, rationale, created_at) "
        "VALUES (%s, %s, 'coordination_only', 'fact:merged', 'test', %s, "
        "'2026-05-01T00:00:00Z')",
        ("YOK-" + str(dependent), "YOK-" + str(blocking), COORD_RATIONALE),
    )
    conn.commit()


@pytest.fixture
def three_item_scenario(conn):
    """Seed three items with mutual coordination_only edges and return
    their pytest-local integer ids.
    """
    seed_target(conn, path_string=SHARED_PATH)
    alpha = _seed_item(conn, item_id=9001)
    beta = _seed_item(conn, item_id=9002)
    gamma = _seed_item(conn, item_id=9003)
    # coordination_only is directionless; one row per pair suffices.
    _add_coord_edge(conn, dependent=alpha, blocking=beta)
    _add_coord_edge(conn, dependent=beta, blocking=gamma)
    _add_coord_edge(conn, dependent=alpha, blocking=gamma)
    return alpha, beta, gamma


def _register_all(conn, items):
    actor_id = local_human(conn)
    return tuple(
        register_for_item(
            conn, item_id=item_id, integration_target="main",
            paths=[SHARED_PATH], actor_id=actor_id,
        )
        for item_id in items
    )


class TestCoordinationOnlyEndToEnd:
    def test_all_three_items_are_frontier_runnable_at_activation(
        self, conn, three_item_scenario,
    ):
        # coordination_only edges remain inert at lifecycle activation.
        blockers = evaluate_batch_gates(conn, "activation")
        for item_id in three_item_scenario:
            assert "YOK-" + str(item_id) not in blockers, (
                f"item {item_id} unexpectedly blocked: {blockers}"
            )

    def test_parallel_registration_lands_all_planned(
        self, conn, three_item_scenario,
    ):
        # Every path claim registers as ``planned`` — no
        # mutex lane, no ``blocked`` row, no ``blocked_reason``.
        a_claim, b_claim, g_claim = _register_all(conn, three_item_scenario)
        for cid in (a_claim, b_claim, g_claim):
            row = get_claim(conn, cid)
            assert row["state"] == "planned", (
                f"claim {cid} expected planned, got {row['state']!r}; "
                f"blocked_reason={row['blocked_reason']!r}"
            )
            assert row["blocked_reason"] is None

    def test_coordination_rationale_persists_on_item_dependencies(
        self, conn, three_item_scenario,
    ):
        # The operator-attested rationale stays on the dep row — the
        # doctor HC reads it to verify intent even though the runtime
        # no longer enforces a path-claim mutex.
        rows = conn.execute(
            "SELECT rationale FROM item_dependencies "
            "WHERE gate_point = 'coordination_only'"
        ).fetchall()
        assert rows
        for row in rows:
            assert COORD_RATIONALE in (row[0] or "")
