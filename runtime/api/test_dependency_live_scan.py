"""Reading only live dependents changes nothing a reader sees.

The waiting graph, its loops and the steering report's chains are built from
unsatisfied edges whose dependent is not finished. A scan that leaves out
finished dependents before judging any edge must give every one of them the
same answer as a scan that judges every edge and discards those afterwards.
"""

from __future__ import annotations

from datetime import datetime, timezone

from yoke_core.domain import frontier_workflow_versions
from yoke_core.domain.dependency_cycles_read import (
    BLOCKING_GATE_POINTS,
    cycles_in,
    live_blocking_edges,
)
from yoke_core.domain.dependency_planning import evaluate_batch_gates
from yoke_core.domain.frontier_dependency_edges import frontier_dependency_graph
from yoke_core.domain.steering_fleet_report_waiting_chains import waiting_chains

from runtime.api.fixtures.backlog import insert_item


def _depend(conn, dependent: int, blocker: int, gate_point: str = "activation"):
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item_id, blocking_item_id, "
        "gate_point, satisfaction, source, rationale, created_at) "
        "VALUES (%s, %s, %s, 'status:done', 'test', '', %s)",
        (
            dependent,
            blocker,
            gate_point,
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
    )
    conn.commit()


def _project(conn, slug: str) -> int:
    return conn.execute("SELECT id FROM projects WHERE slug = %s", (slug,)).fetchone()[0]


def _crossing_state(conn) -> int:
    """A loop and a chain that leave the scope for two items, plus finished
    dependents still holding unsatisfied edges."""
    for item_id, status, project in (
        (1, "implementing", "yoke"),
        (2, "idea", "yoke"),
        (3, "implementing", "other"),
        (4, "idea", "other"),
        (5, "idea", "other"),
        (6, "done", "other"),
        (7, "cancelled", "yoke"),
        (8, "idea", "other"),
    ):
        insert_item(
            conn, id=item_id, workflow_id="issue", status=status, project=project
        )
    _depend(conn, 2, 3, "integration")
    _depend(conn, 3, 4)
    _depend(conn, 4, 2)
    _depend(conn, 5, 3)
    _depend(conn, 5, 1, "closure")
    _depend(conn, 8, 5)
    _depend(conn, 6, 1)
    _depend(conn, 7, 4, "closure")
    return _project(conn, "yoke")


def _full_scan(conn):
    return {
        gate: evaluate_batch_gates(conn, gate, emit_events=False)
        for gate in BLOCKING_GATE_POINTS
    }


def test_finished_dependents_are_left_out_of_the_live_scan(test_db):
    _crossing_state(test_db)

    full = evaluate_batch_gates(test_db, "activation", emit_events=False)
    live = evaluate_batch_gates(
        test_db, "activation", emit_events=False, live_dependents=True
    )

    assert "YOK-6" in full
    assert set(live) == set(full) - {"YOK-6"}
    assert all(live[ref] == full[ref] for ref in live)


def test_live_scan_gives_the_same_edges_loops_and_chains(test_db):
    yoke = _crossing_state(test_db)
    full = _full_scan(test_db)

    live = live_blocking_edges(test_db)
    reference = live_blocking_edges(test_db, gate_blocks=full)

    assert live == reference
    assert cycles_in(live, [yoke]) == cycles_in(reference, [yoke])
    assert cycles_in(live, [yoke])
    assert waiting_chains(test_db, live, yoke) == waiting_chains(
        test_db, reference, yoke
    )
    assert frontier_dependency_graph(test_db, [yoke]) == frontier_dependency_graph(
        test_db, [yoke], gate_blocks=full
    )


def test_each_workflow_version_decodes_once_per_scan(test_db, monkeypatch):
    _crossing_state(test_db)
    decoded = []
    decode = frontier_workflow_versions.workflow_runtime_from_row
    monkeypatch.setattr(
        frontier_workflow_versions,
        "workflow_runtime_from_row",
        lambda row: decoded.append(row["workflow_version_id"]) or decode(row),
    )

    evaluate_batch_gates(test_db, "activation", emit_events=False)
    first = len(decoded)
    for blocker in (1, 3, 4):
        _depend(test_db, 8, blocker)
    decoded.clear()
    evaluate_batch_gates(test_db, "activation", emit_events=False)

    assert len(decoded) == first == len(set(decoded))
