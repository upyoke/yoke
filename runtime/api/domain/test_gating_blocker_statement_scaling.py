"""Quiet-holder dependency facts cost the same however many blockers gate."""

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.statement_counter import CountingConnection
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.session_control_health_facts import gating_blockers


def _add_edges(conn, start, stop):
    """Each dependent waits on its own merged-fact blocker, still implementing."""
    for index in range(start, stop):
        dependent, blocker = 9900 + 2 * index, 9901 + 2 * index
        for item in (dependent, blocker):
            insert_item(
                conn, id=item, project_sequence=item, workflow_id="dash",
                status="implementing",
            )
        conn.execute(
            "INSERT INTO item_dependencies (dependent_item_id,blocking_item_id,"
            "gate_point,satisfaction,source,created_at) "
            "VALUES (%s,%s,'activation','fact:merged','test','2026-01-01T00:00:00Z')",
            (dependent, blocker),
        )
    conn.commit()


def test_gating_blocker_reads_do_not_scale_with_edges(test_db):
    counts = []
    seeded = 0
    for size in (1, 10, 30):
        _add_edges(test_db, seeded, size)
        seeded = size
        dependents = [9900 + 2 * index for index in range(size)]
        counted = CountingConnection(test_db)
        blockers = gating_blockers(counted, dependents)
        counts.append(counted.count)
        assert set(blockers) == set(dependents)
        for dependent in dependents:
            assert blockers[dependent]["item"] == render_item_ref(test_db, dependent)
            assert blockers[dependent]["blocking_item"] == render_item_ref(
                test_db, dependent + 1
            )
            assert blockers[dependent]["gate_point"] == "activation"
    assert counts[0] == counts[1] == counts[2], counts
