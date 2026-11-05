"""Block flags distinguish satisfied dependencies from outstanding waits."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.session_holdings import insert_session
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain import backlog_update_op
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers.items_flags import handle_block
from yoke_core.domain.project_identity import render_item_ref


SESSION = "dependency-block-session"


@pytest.fixture(autouse=True)
def _isolate_calls(test_db, monkeypatch):
    insert_session(test_db, SESSION)
    monkeypatch.setattr(backlog_update_op, "run_post_db_sync", lambda **_kwargs: 0)


def _add_dependency(conn, dependent, blocking, gate_point):
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id, blocking_item_id, gate_point, satisfaction, "
        "source, created_at) VALUES (%s, %s, %s, 'status:done', 'operator', %s)",
        (dependent, blocking, gate_point, iso8601_now()),
    )
    conn.commit()


def _block(item_id):
    return handle_block(
        FunctionCallRequest(
            function="items.block.run",
            actor=ActorContext(actor_id="1", session_id=SESSION),
            target=TargetRef(kind="item", item_id=item_id),
            payload={"reason": "Awaiting human decision"},
        )
    )


@pytest.mark.parametrize("gate_point", ("activation", "integration", "closure"))
def test_satisfied_dependency_allows_unrelated_block(test_db, gate_point):
    dependent, satisfied = 8410, 8411
    insert_item(test_db, id=dependent, status="implementing")
    insert_item(test_db, id=satisfied, status="done")
    _add_dependency(test_db, dependent, satisfied, gate_point)

    outcome = _block(dependent)

    assert outcome.primary_success, outcome.error
    row = test_db.execute(
        "SELECT blocked, blocked_reason, status FROM items WHERE id = %s",
        (dependent,),
    ).fetchone()
    assert bool(row["blocked"])
    assert row["blocked_reason"] == "Awaiting human decision"
    assert row["status"] == "implementing"


@pytest.mark.parametrize("gate_point", ("activation", "integration", "closure"))
def test_unsatisfied_dependency_refuses_only_unsatisfied_edge(test_db, gate_point):
    dependent, satisfied, unsatisfied, coordinated = 8420, 8421, 8422, 8423
    insert_item(test_db, id=dependent, status="implementing")
    insert_item(test_db, id=satisfied, status="done")
    insert_item(test_db, id=unsatisfied, status="idea")
    insert_item(test_db, id=coordinated, status="idea")
    _add_dependency(test_db, dependent, satisfied, gate_point)
    _add_dependency(test_db, dependent, unsatisfied, gate_point)
    _add_dependency(test_db, dependent, coordinated, "coordination_only")

    outcome = _block(dependent)

    assert not outcome.primary_success
    assert outcome.error.code == "dependency_wait_on_edge"
    message = outcome.error.message
    assert render_item_ref(test_db, unsatisfied) in message
    assert render_item_ref(test_db, satisfied) not in message
    assert render_item_ref(test_db, coordinated) not in message
    assert "Wait for the blocking item" in message
    assert "yoke items dependency remove" in message
    row = test_db.execute(
        "SELECT blocked, blocked_reason FROM items WHERE id = %s", (dependent,)
    ).fetchone()
    assert not row["blocked"]
    assert row["blocked_reason"] is None
