"""Dependency deadlocks: found once on the backend, refused at every write.

The pure detector runs on hand-built edges; the refusal runs on the
``test_db`` fixture through the domain commands and the registered handler,
so each assertion is what an author or a steering seat actually sees.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.dependency_cycles import (
    DependencyCycle,
    DependencyCycleError,
    WaitEdge,
    find_cycles,
)
from yoke_core.domain.dependency_cycles_read import dependency_cycles
from yoke_core.domain.handlers.item_dependency_writes import (
    handle_item_dependency_add,
    handle_item_dependency_update,
)
from yoke_core.domain.item_dependency import cmd_dependency_add, cmd_dependency_update


def _wait(number, dependent, blocking, gate="activation", sat="status:done"):
    return WaitEdge(number, dependent, blocking, gate, sat)


def test_a_ring_is_named_in_loop_order_with_what_it_strands():
    edges = [
        _wait(6597, "YOK-3975", "YOK-3973"),
        _wait(8220, "YOK-3965", "YOK-3975", "integration", "fact:merged"),
        _wait(8221, "YOK-3973", "YOK-3965", "integration", "fact:merged"),
        _wait(9001, "YOK-4035", "YOK-3965"),
        _wait(9002, "PLAT-223", "YOK-4035"),
        _wait(9003, "YOK-5000", "YOK-6000"),
    ]

    [cycle] = find_cycles(edges)

    assert cycle.items == ("YOK-3965", "YOK-3975", "YOK-3973")
    assert [edge.dependency_id for edge in cycle.edges] == [8220, 6597, 8221]
    assert cycle.stranded == ("PLAT-223", "YOK-4035")
    assert cycle.describe() == (
        "YOK-3965 → YOK-3975 → YOK-3973 → YOK-3965: "
        "#8220 YOK-3965 waits on YOK-3975 (integration, fact:merged); "
        "#6597 YOK-3975 waits on YOK-3973 (activation, status:done); "
        "#8221 YOK-3973 waits on YOK-3965 (integration, fact:merged); "
        "strands PLAT-223, YOK-4035"
    )
    assert DependencyCycle.from_dict(cycle.to_dict()) == cycle


def test_a_self_edge_is_a_loop_of_one_and_a_chain_is_none():
    assert find_cycles([_wait(1, "A-1", "A-2"), _wait(2, "A-2", "A-3")]) == []
    [cycle] = find_cycles([_wait(3, "A-1", "A-1")])
    assert cycle.loop_text() == "A-1 waits on itself"


def test_separate_loops_are_separate_and_deep_graphs_do_not_recurse():
    chain = [_wait(n, f"C-{n}", f"C-{n + 1}") for n in range(5000)]
    loops = [_wait(1, "A-1", "A-2"), _wait(2, "A-2", "A-1")]
    loops += [_wait(3, "B-1", "B-2"), _wait(4, "B-2", "B-1")]
    cycles = find_cycles([*chain, _wait(5000, "C-5000", "C-0"), *loops])
    assert [cycle.key for cycle in cycles][:2] == ["A-1,A-2", "B-1,B-2"]
    assert len(cycles[2].items) == 5001


def _items(conn, *ids, status="idea"):
    for item_id in ids:
        insert_item(conn, id=item_id, title=f"item {item_id}", status=status)
    conn.commit()


def _count(conn) -> int:
    return int(conn.execute("SELECT count(*) FROM item_dependencies").fetchone()[0])


def test_an_add_that_closes_a_loop_refuses_naming_it_and_writes_nothing(test_db):
    _items(test_db, 1, 2, 3, 4)
    first = cmd_dependency_add(test_db, "YOK-1", "YOK-2", "operator")
    second = cmd_dependency_add(
        test_db, "YOK-2", "YOK-3", "conduct", gate_point="integration"
    )
    cmd_dependency_add(test_db, "YOK-4", "YOK-1", "operator")
    before = _count(test_db)

    with pytest.raises(DependencyCycleError) as refused:
        cmd_dependency_add(
            test_db, "YOK-3", "YOK-1", "refine", gate_point="integration"
        )

    message = str(refused.value)
    assert message.startswith(
        "dependency_cycle: adding YOK-3 waiting on YOK-1 at integration"
    )
    assert f"#{first.edge.dependency_id} YOK-1 waits on YOK-2" in message
    assert f"#{second.edge.dependency_id} YOK-2 waits on YOK-3" in message
    assert "proposed YOK-3 waits on YOK-1 (integration, fact:merged)" in message
    assert "strands YOK-4" in message
    assert "--gate-point coordination_only" in message
    assert "yoke say --steering" in message
    assert _count(test_db) == before
    assert dependency_cycles(test_db) == []


def test_coordination_only_edges_never_close_a_loop(test_db):
    _items(test_db, 1, 2)
    cmd_dependency_add(test_db, "YOK-1", "YOK-2", "operator")
    cmd_dependency_add(
        test_db, "YOK-2", "YOK-1", "refine", gate_point="coordination_only"
    )
    assert dependency_cycles(test_db) == []

    with pytest.raises(DependencyCycleError):
        cmd_dependency_update(
            test_db,
            "YOK-2",
            "YOK-1",
            match_gate_point="coordination_only",
            gate_point="activation",
        )
    gates = test_db.execute(
        "SELECT gate_point FROM item_dependencies WHERE dependent_item_id = 2"
    ).fetchall()
    assert [row[0] for row in gates] == ["coordination_only"]


def test_a_satisfied_edge_and_a_terminal_item_never_close_a_loop(test_db):
    _items(test_db, 1, 2)
    _items(test_db, 3, status="done")
    cmd_dependency_add(test_db, "YOK-1", "YOK-3", "operator")
    cmd_dependency_add(test_db, "YOK-3", "YOK-1", "operator")
    cmd_dependency_add(test_db, "YOK-1", "YOK-2", "operator")
    test_db.execute(
        "UPDATE items SET status = 'done' WHERE id = 2",
    )
    test_db.commit()
    cmd_dependency_add(test_db, "YOK-2", "YOK-1", "operator")
    assert dependency_cycles(test_db) == []


def test_a_stored_loop_is_found_and_breaking_one_edge_clears_it(test_db):
    _items(test_db, 1, 2)
    cmd_dependency_add(test_db, "YOK-1", "YOK-2", "operator")
    test_db.execute(
        "INSERT INTO item_dependencies (dependent_item_id, blocking_item_id, "
        "gate_point, satisfaction, source, rationale, created_at) "
        "VALUES (2, 1, 'activation', 'status:done', 'operator', '', now())"
    )
    test_db.commit()
    [cycle] = dependency_cycles(test_db)
    assert cycle.items == ("YOK-1", "YOK-2")

    cmd_dependency_update(test_db, "YOK-2", "YOK-1", gate_point="coordination_only")
    assert dependency_cycles(test_db) == []


def _request(function, item_id, payload):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def test_handlers_name_the_refusal_with_its_own_code(test_db):
    _items(test_db, 1, 2)
    added = handle_item_dependency_add(
        _request(
            "items.dependency.add",
            1,
            {"blocking_item": "YOK-2", "source": "operator", "rationale": "order"},
        )
    )
    assert added.primary_success, added.error

    refused = handle_item_dependency_add(
        _request(
            "items.dependency.add",
            2,
            {"blocking_item": "YOK-1", "source": "refine", "rationale": "loop"},
        )
    )
    assert refused.primary_success is False
    assert refused.error.code == "dependency_cycle"
    assert "YOK-2 waits on YOK-1" in refused.error.message

    handle_item_dependency_add(
        _request(
            "items.dependency.add",
            2,
            {
                "blocking_item": "YOK-1",
                "source": "refine",
                "rationale": "independent",
                "gate_point": "coordination_only",
            },
        )
    )
    regated = handle_item_dependency_update(
        _request(
            "items.dependency.update",
            2,
            {
                "blocking_item": "YOK-1",
                "match_gate_point": "coordination_only",
                "gate_point": "activation",
            },
        )
    )
    assert regated.primary_success is False
    assert regated.error.code == "dependency_cycle"


def test_charge_schedule_serves_loops_narrowed_to_a_seat(test_db):
    from yoke_core.domain.handlers.sessions_charge_schedule import _dependency_cycles

    _items(test_db, 1, 2, 3)
    cmd_dependency_add(test_db, "YOK-1", "YOK-2", "operator")
    test_db.execute(
        "INSERT INTO item_dependencies (dependent_item_id, blocking_item_id, "
        "gate_point, satisfaction, source, rationale, created_at) "
        "VALUES (2, 1, 'activation', 'status:done', 'operator', '', now())"
    )
    test_db.commit()
    project = int(
        test_db.execute("SELECT project_id FROM items WHERE id = 1").fetchone()[0]
    )

    [row] = _dependency_cycles(test_db, [project], None)
    assert row["items"] == ["YOK-1", "YOK-2"]
    assert _dependency_cycles(test_db, [project], {2})[0]["items"] == row["items"]
    assert _dependency_cycles(test_db, [project], {3}) == []
