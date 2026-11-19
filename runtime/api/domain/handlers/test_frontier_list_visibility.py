"""``frontier.list`` names nothing from a project its reader cannot see.

A viewer of one project reads the Frontier over every project by default.
Rows, edges and deadlocks from other projects stay out of the answer, and
a visible item waiting on hidden work still shows as waiting without
naming that work. Local and admin-unscoped reads keep the whole graph.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.frontier_blocked_rows import HIDDEN_BLOCKER_WHY
from yoke_core.domain.frontier_list_read import list_frontier
from yoke_core.domain.function_authz_scope import (
    ACTOR_SESSION,
    AuthzSpec,
    classify,
)
from yoke_core.domain.handlers.frontier_list import handle_frontier_list

SECRET = "HIDDEN PLATFORM WORK"


def _depend(conn, dependent: int, blocker: int, gate_point: str = "activation"):
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item_id, blocking_item_id, "
        "gate_point, satisfaction, source, rationale, created_at) "
        "VALUES (%s, %s, %s, 'status:done', 'test', %s, %s)",
        (
            dependent,
            blocker,
            gate_point,
            f"{SECRET} rationale" if max(dependent, blocker) > 10 else "ordering",
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
    )
    conn.commit()


def _project_id(conn, item_id: int) -> int:
    return int(
        conn.execute("SELECT project_id FROM items WHERE id = %s", (item_id,))
        .fetchone()[0]
    )


@pytest.fixture
def world(test_db):
    """A visible item gated by hidden work, and a hidden loop stranding one."""
    insert_item(test_db, id=1, title="visible start", status="idea")
    insert_item(test_db, id=2, title="visible landing", status="idea")
    insert_item(test_db, id=3, title="visible stranded", status="idea")
    insert_item(test_db, id=4, title="visible pair", status="idea")
    for item_id in (11, 12, 13):
        insert_item(
            test_db,
            id=item_id,
            title=f"{SECRET} {item_id}",
            status="implementing" if item_id == 11 else "idea",
            project="platform",
        )
    _depend(test_db, 1, 11)
    _depend(test_db, 2, 11, gate_point="integration")
    _depend(test_db, 12, 13)
    _depend(test_db, 13, 12)
    _depend(test_db, 3, 12)
    _depend(test_db, 12, 4)
    _depend(test_db, 4, 1)
    yoke = _project_id(test_db, 1)
    hidden = _project_id(test_db, 11)
    assert yoke != hidden
    hidden_refs = {
        row["blocking_item"]
        for row in list_frontier()["dependency_edges"]
        if row["blocking_project_id"] == hidden
    }
    return test_db, yoke, hidden, hidden_refs


def test_a_viewer_reads_only_visible_rows_edges_and_cycles(world):
    _conn, yoke, hidden, hidden_refs = world
    assert hidden_refs

    result = list_frontier(visible_project_ids={yoke})

    rows = [*result["ready_rows"], *result["blocked_rows"]]
    assert {row["project_id"] for row in rows} == {yoke}
    edges = {(r["title"], r["gate_point"]): r for r in result["blocked_rows"]}
    start = edges["visible start", "activation"]
    assert start["holds_pickup"] is True
    assert start["blocking_item"] == ""
    assert start["blocking_project_id"] is None
    assert start["blocking_project_sequence"] is None
    assert start["why"] == HIDDEN_BLOCKER_WHY
    landing = edges["visible landing", "integration"]
    assert (landing["blocking_item"], landing["why"]) == ("", HIDDEN_BLOCKER_WHY)
    for edge in result["dependency_edges"]:
        assert edge["blocking_project_id"] == yoke
        assert edge["dependent_project_id"] == yoke
    assert result["dependency_cycles"] == []
    served = json.dumps(result, default=str)
    assert SECRET not in served
    for ref in hidden_refs:
        assert f'"{ref}"' not in served


def test_local_and_admin_reads_keep_the_whole_graph(world):
    _conn, yoke, hidden, hidden_refs = world

    result = list_frontier()

    assert {e["blocking_project_id"] for e in result["dependency_edges"]} >= {
        yoke,
        hidden,
    }
    assert result["dependency_cycles"]
    start = next(
        r
        for r in result["blocked_rows"]
        if (r["title"], r["gate_point"]) == ("visible start", "activation")
    )
    assert start["blocking_item"] in hidden_refs
    assert start["blocking_project_id"] == hidden


def test_a_named_hidden_project_is_refused_like_an_unknown_one(world):
    _conn, yoke, _hidden, _refs = world

    with pytest.raises(ValueError) as refused:
        list_frontier(project="platform", visible_project_ids={yoke})

    assert "Unknown project 'platform'" in str(refused.value)
    assert "yoke projects list" in str(refused.value)
    named = list_frontier(project="yoke", visible_project_ids={yoke})
    assert {row["project_id"] for row in named["blocked_rows"]} == {yoke}


def test_frontier_list_is_an_actor_session_read():
    spec = classify("frontier.list", side_effects=False, project_permission=None)
    assert spec == AuthzSpec(ACTOR_SESSION, None)


def test_the_handler_scopes_an_actor_to_its_projects(world):
    conn, yoke, _hidden, _refs = world
    viewer = seed_human_actor(conn, "Frontier viewer")
    role = conn.execute("SELECT id FROM roles WHERE name = 'viewer'").fetchone()[0]
    conn.execute(
        "INSERT INTO actor_project_roles (actor_id, project_id, role_id, "
        "granted_at) VALUES (%s, %s, %s, now())",
        (viewer, yoke, role),
    )
    conn.commit()
    request = FunctionCallRequest(
        function="frontier.list",
        actor=ActorContext(actor_id=str(viewer), session_id=""),
        target=TargetRef(kind="global"),
        payload={},
    )

    outcome = handle_frontier_list(request)

    assert outcome.primary_success, outcome.error
    served = json.dumps(outcome.result_payload, default=str)
    assert SECRET not in served
    refused = handle_frontier_list(
        request.model_copy(update={"payload": {"project": "platform"}})
    )
    assert refused.error.code == "not_found"
