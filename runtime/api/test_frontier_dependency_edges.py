"""The Frontier's dependency edges: every unsatisfied blocking edge, as data.

Real-DB coverage on the ``test_db`` fixture. The Waiting graph draws these
rows directly, so each assertion is a fact the graph shows: which gate an edge
holds, what clears it, why it exists, where the blocker is, and whether it can
ever clear.
"""

from __future__ import annotations

from datetime import datetime, timezone

from yoke_core.domain.dependency_planning import BlockerDetail
from yoke_core.domain.frontier_dependency_edges import (
    FRONTIER_CYCLE_FIELDS,
    FRONTIER_EDGE_FIELDS,
    frontier_dependency_graph,
)
from yoke_core.domain.frontier_list_read import list_frontier

from runtime.api.fixtures.backlog import insert_item


def frontier_dependency_edges(conn, *args, **kwargs):
    return frontier_dependency_graph(conn, *args, **kwargs)["dependency_edges"]


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _depend(
    conn,
    dependent: int,
    blocker: int,
    *,
    gate_point: str = "activation",
    satisfaction: str = "status:done",
    rationale: str = "",
) -> None:
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item_id, blocking_item_id, "
        "gate_point, satisfaction, source, rationale, created_at) "
        "VALUES (%s, %s, %s, %s, 'test', %s, %s)",
        (dependent, blocker, gate_point, satisfaction, rationale, _iso()),
    )
    conn.commit()


def _items(conn, *specs) -> None:
    for item_id, status in specs:
        insert_item(
            conn,
            id=item_id,
            title=f"item {item_id}",
            workflow_id="issue",
            status=status,
        )


def _pairs(edges) -> set[tuple[str, str, str]]:
    return {
        (edge["blocking_item"], edge["dependent_item"], edge["gate_point"])
        for edge in edges
    }


def test_unsatisfied_edges_at_every_gate_carry_their_rationale(test_db):
    _items(test_db, (1, "implementing"), (2, "idea"), (3, "idea"), (4, "idea"))
    _depend(test_db, 2, 1, gate_point="activation", rationale="starts after")
    _depend(test_db, 3, 1, gate_point="integration", rationale="lands after")
    _depend(test_db, 4, 1, gate_point="closure", rationale="closes after")

    edges = frontier_dependency_edges(test_db)

    assert _pairs(edges) == {
        ("YOK-1", "YOK-2", "activation"),
        ("YOK-1", "YOK-3", "integration"),
        ("YOK-1", "YOK-4", "closure"),
    }
    by_dependent = {edge["dependent_item"]: edge for edge in edges}
    assert by_dependent["YOK-2"]["rationale"] == "starts after"
    assert by_dependent["YOK-3"]["rationale"] == "lands after"
    assert by_dependent["YOK-4"]["rationale"] == "closes after"
    edge = by_dependent["YOK-2"]
    assert set(edge) == set(FRONTIER_EDGE_FIELDS)
    assert edge["satisfaction"] == "status:done"
    assert edge["blocking_stage"] == "implementing"
    assert edge["blocking_title"] == "item 1"
    assert edge["blocking_terminal"] is False
    assert edge["blocking_abandoned"] is False
    assert edge["blocking_project_id"] == 1
    assert edge["blocking_project_sequence"] == 1
    assert edge["dependent_project_sequence"] == 2
    assert edge["environment"] is None


def test_an_item_waiting_on_several_blockers_has_one_edge_each(test_db):
    _items(test_db, (1, "implementing"), (2, "implementing"), (3, "idea"))
    _depend(test_db, 3, 1)
    _depend(test_db, 3, 2, satisfaction="fact:merged")

    assert _pairs(frontier_dependency_edges(test_db)) == {
        ("YOK-1", "YOK-3", "activation"),
        ("YOK-2", "YOK-3", "activation"),
    }


def test_satisfied_and_coordination_only_edges_are_not_returned(test_db):
    _items(test_db, (1, "done"), (2, "idea"), (3, "implementing"), (4, "idea"))
    _depend(test_db, 2, 1)
    _depend(test_db, 4, 3, gate_point="coordination_only")

    assert frontier_dependency_edges(test_db) == []


def test_a_stored_loop_serves_its_edges_and_the_backend_deadlock(test_db):
    _items(test_db, (1, "idea"), (2, "idea"), (3, "idea"))
    _depend(test_db, 1, 2)
    _depend(test_db, 2, 1)
    _depend(test_db, 3, 2)

    graph = frontier_dependency_graph(test_db)

    assert _pairs(graph["dependency_edges"]) == {
        ("YOK-2", "YOK-1", "activation"),
        ("YOK-1", "YOK-2", "activation"),
        ("YOK-2", "YOK-3", "activation"),
    }
    [cycle] = graph["dependency_cycles"]
    assert set(cycle) == set(FRONTIER_CYCLE_FIELDS)
    assert cycle["items"] == ["YOK-1", "YOK-2"]
    assert [edge["dependent_item"] for edge in cycle["edges"]] == ["YOK-1", "YOK-2"]
    assert all(isinstance(edge["dependency_id"], int) for edge in cycle["edges"])
    assert cycle["stranded"] == ["YOK-3"]


def test_a_terminal_blocker_is_named_and_a_terminal_dependent_dropped(test_db):
    _items(test_db, (1, "cancelled"), (2, "idea"), (3, "implementing"))
    insert_item(test_db, id=4, title="over", workflow_id="issue", status="cancelled")
    _depend(test_db, 2, 1, satisfaction="fact:merged")
    _depend(test_db, 4, 3)

    edges = frontier_dependency_edges(test_db)

    assert _pairs(edges) == {("YOK-1", "YOK-2", "activation")}
    assert edges[0]["blocking_stage"] == "cancelled"
    assert edges[0]["blocking_terminal"] is True
    # Cancelled ends the blocker without completing it: the edge never clears.
    assert edges[0]["blocking_abandoned"] is True


def test_a_completed_blocker_is_told_apart_from_an_abandoned_one(test_db):
    _items(test_db, (1, "done"), (2, "idea"))
    _depend(test_db, 2, 1, satisfaction="fact:deployed:prod")

    edges = frontier_dependency_edges(test_db)

    assert _pairs(edges) == {("YOK-1", "YOK-2", "activation")}
    assert edges[0]["blocking_terminal"] is True
    assert edges[0]["blocking_abandoned"] is False


def test_an_item_depending_on_itself_is_returned_as_its_own_cycle(test_db):
    _items(test_db, (1, "idea"))
    _depend(test_db, 1, 1)

    assert _pairs(frontier_dependency_edges(test_db)) == {
        ("YOK-1", "YOK-1", "activation")
    }


def test_a_blocker_that_no_longer_resolves_still_draws_its_edge(test_db):
    _items(test_db, (2, "idea"))
    unresolved = BlockerDetail(
        blocking_item="GONE-99",
        blocking_status=None,
        gate_point="activation",
        satisfaction="fact:merged",
        rationale="waits on retired work",
        reason="",
    )

    edges = frontier_dependency_edges(
        test_db,
        gate_blocks={
            "activation": {"YOK-2": [unresolved]},
            "integration": {},
            "closure": {},
        },
    )

    assert len(edges) == 1
    edge = edges[0]
    assert (edge["blocking_item"], edge["dependent_item"]) == ("GONE-99", "YOK-2")
    assert edge["rationale"] == "waits on retired work"
    assert edge["blocking_stage"] is None
    assert edge["blocking_title"] is None
    assert edge["blocking_project_id"] is None
    assert edge["blocking_terminal"] is False
    assert edge["environment"] is None


def _environments(conn) -> None:
    now = _iso()
    conn.execute(
        "INSERT INTO sites (id, project_id, name, created_at) "
        "VALUES (901, 1, 'yoke-site', %s)",
        (now,),
    )
    conn.execute(
        "INSERT INTO environments (id, site, project_id, name, created_at) "
        "VALUES (911, 901, 1, 'stage', %s), (912, 901, 1, 'prod', %s)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO deployment_flows (id, project_id, name, stages, status, "
        "target_tier, target_environment_id, takes_delivery_custody, created_at) "
        "VALUES ('edge-stage-flow', 1, 'edge-stage-flow', '[]', 'active', "
        "'persistent', 911, "
        "0, %s)",
        (now,),
    )
    conn.commit()


def test_a_deployed_edge_says_whether_any_flow_reaches_its_environment(test_db):
    _environments(test_db)
    _items(test_db, (1, "implementing"), (2, "idea"), (3, "idea"))
    _depend(test_db, 2, 1, satisfaction="fact:deployed:stage")
    _depend(test_db, 3, 1, satisfaction="fact:deployed:prod")

    by_dependent = {
        edge["dependent_item"]: edge for edge in frontier_dependency_edges(test_db)
    }

    assert by_dependent["YOK-2"]["environment"] == {
        "name": "stage",
        "delivery_state": "not deployed",
        "in_delivery_flow": True,
    }
    # prod is registered, but no active flow of the project delivers there,
    # so nothing can ever make the blocker live on it.
    assert by_dependent["YOK-3"]["environment"] == {
        "name": "prod",
        "delivery_state": "not deployed",
        "in_delivery_flow": False,
    }


def test_a_project_scope_keeps_chains_that_cross_into_it(test_db):
    insert_item(
        test_db, id=1, workflow_id="issue", status="implementing", project="other"
    )
    insert_item(test_db, id=2, workflow_id="issue", status="idea", project="yoke")
    insert_item(
        test_db, id=3, workflow_id="issue", status="implementing", project="other"
    )
    insert_item(test_db, id=4, workflow_id="issue", status="idea", project="other")
    _depend(test_db, 2, 1)
    _depend(test_db, 4, 3)
    yoke_id = int(
        test_db.execute("SELECT id FROM projects WHERE slug = 'yoke'").fetchone()[0]
    )

    edges = frontier_dependency_edges(test_db, [yoke_id])

    assert [(edge["blocking_item"], edge["dependent_item"]) for edge in edges] == [
        ("YOK-1", "YOK-2"),
    ]


def test_frontier_list_serves_the_edges_beside_its_rows(test_db):
    _items(test_db, (1, "implementing"), (2, "idea"))
    _depend(test_db, 2, 1, rationale="ordering")

    result = list_frontier()

    assert result["fields"]["dependency_edges"] == list(FRONTIER_EDGE_FIELDS)
    assert _pairs(result["dependency_edges"]) == {("YOK-1", "YOK-2", "activation")}
    assert result["fields"]["dependency_cycles"] == list(FRONTIER_CYCLE_FIELDS)
    assert result["dependency_cycles"] == []


def test_a_scoped_read_draws_a_loop_that_holds_or_strands_its_work(test_db):
    insert_item(test_db, id=1, workflow_id="issue", status="idea", project="yoke")
    insert_item(test_db, id=2, workflow_id="issue", status="idea", project="other")
    insert_item(test_db, id=3, workflow_id="issue", status="idea", project="other")
    _depend(test_db, 1, 2)
    _depend(test_db, 2, 3)
    _depend(test_db, 3, 2)
    yoke_id = int(
        test_db.execute("SELECT id FROM projects WHERE slug = 'yoke'").fetchone()[0]
    )
    other_id = int(
        test_db.execute("SELECT id FROM projects WHERE slug = 'other'").fetchone()[0]
    )

    insert_item(test_db, id=4, workflow_id="issue", status="idea", project="third")
    third_id = int(
        test_db.execute("SELECT project_id FROM items WHERE id = 4").fetchone()[0]
    )

    for scope in ([other_id], [yoke_id]):
        graph = frontier_dependency_graph(test_db, scope)
        [cycle] = graph["dependency_cycles"]
        assert cycle["stranded"] == ["YOK-1"]
        assert {
            (e["blocking_item"], e["dependent_item"]) for e in cycle["edges"]
        } <= {(e["blocking_item"], e["dependent_item"]) for e in graph["dependency_edges"]}
    assert frontier_dependency_graph(test_db, [third_id])["dependency_cycles"] == []
