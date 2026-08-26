"""Terminal lifecycle release for item-owned migration territory."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.strategy_execution_test_support import (
    seed_blitz_item,
    seed_session_claim,
)
from runtime.api.fixtures.pg_testdb import connect_test_database
from yoke_core.domain.coordination_leases import active_lease, get_lease
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.item_terminal_resources import release_for_terminal_transition
from yoke_core.domain.migration_territory_lease import enter
from yoke_core.domain.schema_init_tables import create_governed_tables
from yoke_core.domain.workflow_item_binding_lock import lock_item_workflow_bindings
from yoke_core.domain.work_claim_targets import make_item_target


MODEL = "primary"
LEASE_KEY = f"LIVE_DB_MIGRATION:{MODEL}"


@pytest.fixture(autouse=True)
def _governed_tables(test_db):
    create_governed_tables(test_db)


def _profile(model_name: str = MODEL) -> str:
    return json.dumps(
        {
            "state": "declared",
            "model_name": model_name,
            "mutation_intent": "apply",
            "migration_modules": ["add_terminal_column"],
            "compatibility_class": "pre_merge_safe",
            "migration_strategy": "additive_only",
        }
    )


def _seed_owner(conn, *, item_id: int, session_id: str) -> int:
    seed_blitz_item(conn, item_id, item_id)
    seed_session_claim(conn, item_id, session_id)
    conn.execute(
        "UPDATE items SET db_mutation_profile=%s WHERE id=%s",
        (_profile(), item_id),
    )
    conn.commit()
    return enter(
        conn,
        project=1,
        model_name=MODEL,
        item_id=item_id,
        session_id=session_id,
    ).id


def _transition(conn, *, item_id: int, target_status: str):
    lock_item_workflow_bindings(conn, (item_id,))
    conn.execute(
        "UPDATE items SET status=%s, updated_at=%s WHERE id=%s",
        (target_status, iso8601_now(), item_id),
    )
    return release_for_terminal_transition(
        conn,
        item_id=item_id,
        target_status=target_status,
        session_id=None,
        actor_id=None,
    )


@pytest.mark.parametrize("target_status", ["done", "cancelled", "stopped"])
def test_terminal_status_releases_owned_model_territory(test_db, target_status):
    item_id = {"done": 4201, "cancelled": 4202, "stopped": 4203}[target_status]
    lease_id = _seed_owner(test_db, item_id=item_id, session_id="terminal-owner")

    receipt = _transition(test_db, item_id=item_id, target_status=target_status)
    test_db.commit()

    assert receipt.migration_territories_released == 1
    assert active_lease(test_db, 1, LEASE_KEY) is None
    settled = get_lease(test_db, lease_id)
    assert settled.release_reason == f"item-terminal:{target_status}"


def test_terminal_status_does_not_release_foreign_holder(test_db):
    item_id = 4204
    _seed_owner(test_db, item_id=item_id, session_id="item-owner")
    owned = active_lease(test_db, 1, LEASE_KEY)
    assert owned is not None
    test_db.execute(
        "UPDATE coordination_leases SET owner_item_id=4299, "
        "session_id='foreign-owner' WHERE id=%s",
        (owned.id,),
    )
    test_db.commit()

    receipt = _transition(test_db, item_id=item_id, target_status="cancelled")
    test_db.commit()

    assert receipt.migration_territories_released == 0
    held = active_lease(test_db, 1, LEASE_KEY)
    assert held is not None and held.session_id == "foreign-owner"


def test_terminal_status_uses_historical_owner_after_claim_release(test_db):
    item_id = 4208
    lease_id = _seed_owner(test_db, item_id=item_id, session_id="merged-owner")
    target = make_item_target(item_id)
    test_db.execute(
        "UPDATE work_claims SET released_at=%s, release_reason='completed' "
        "WHERE target_kind=%s AND scope=%s",
        (iso8601_now(), target.kind, target.scope_json()),
    )
    test_db.commit()

    receipt = _transition(test_db, item_id=item_id, target_status="done")
    test_db.commit()

    assert receipt.migration_territories_released == 1
    assert get_lease(test_db, lease_id).release_reason == "item-terminal:done"


def test_terminal_release_follows_item_owner_not_shared_session(test_db):
    first_id, second_id = 4205, 4206
    lease_id = _seed_owner(test_db, item_id=first_id, session_id="shared-owner")
    seed_blitz_item(test_db, second_id, second_id)
    test_db.execute(
        "UPDATE items SET db_mutation_profile=%s WHERE id=%s",
        (_profile(), second_id),
    )
    now = iso8601_now()
    target = make_item_target(second_id)
    test_db.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat) "
        "VALUES ('shared-owner', %s, %s, 'exclusive', %s, %s)",
        (target.kind, target.scope_json(), now, now),
    )
    test_db.commit()

    first = _transition(test_db, item_id=first_id, target_status="done")
    test_db.commit()
    assert first.migration_territories_released == 1
    assert get_lease(test_db, lease_id).release_reason == "item-terminal:done"
    assert active_lease(test_db, 1, LEASE_KEY) is None

    second = _transition(test_db, item_id=second_id, target_status="stopped")
    test_db.commit()
    assert second.migration_territories_released == 0


def test_terminal_release_rolls_back_with_status_transition(test_db):
    item_id = 4207
    lease_id = _seed_owner(test_db, item_id=item_id, session_id="rollback-owner")
    transition_conn = connect_test_database(str(test_db.info.dbname))
    try:
        receipt = _transition(
            transition_conn,
            item_id=item_id,
            target_status="cancelled",
        )
        assert receipt.migration_territories_released == 1
        assert get_lease(transition_conn, lease_id).released_at is not None
        transition_conn.rollback()
    finally:
        transition_conn.close()

    assert active_lease(test_db, 1, LEASE_KEY) is not None
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s",
        (item_id,),
    ).fetchone()
    assert str(status[0]) == "implementing"
