"""``sessions.list`` projects every live claim and coordination lease.

Companion to the handler tests: those stay at the authored-file cap, so
the holdings projection (leases, per-claim drill-in coordinates) lives
here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.api.fixtures.backlog import insert_item, insert_item_worktree
from yoke_core.domain.sessions_list_read import list_sessions


def _iso(minutes_ago: int = 0) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _insert_session(conn, session_id: str, *, current_item_id: str | None = None) -> None:
    now = _iso()
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id, executor, provider, model, execution_lane, workspace, "
        "project_id, mode, offered_at, last_heartbeat, current_item_id"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            session_id,
            "claude-code",
            "anthropic",
            "test-model",
            "primary",
            "/tmp/workspace",
            1,
            "wait",
            now,
            now,
            current_item_id,
        ),
    )
    conn.commit()


def _insert_item_claim(conn, session_id: str, item_id: int) -> None:
    conn.execute(
        "INSERT INTO work_claims ("
        "session_id, target_kind, item_id, claimed_at, last_heartbeat, reason"
        ") VALUES (%s, 'item', %s, %s, %s, %s)",
        (session_id, item_id, _iso(), _iso(), "implementation"),
    )
    conn.commit()


def _insert_lease(
    conn,
    *,
    session_id: str,
    lease_key: str,
    owner_kind: str = "session",
    owner_session_id: str | None = None,
    owner_item_id: int | None = None,
    released_at: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO coordination_leases ("
        "project_id, lease_key, session_id, acquired_at, heartbeat_at, "
        "owner_kind, owner_session_id, owner_item_id, released_at, "
        "release_reason"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            1,
            lease_key,
            session_id,
            _iso(),
            _iso(),
            owner_kind,
            owner_session_id,
            owner_item_id,
            released_at,
            "completed" if released_at else None,
        ),
    )
    conn.commit()


def test_session_row_carries_empty_leases_when_none_are_held(test_db):
    _insert_session(test_db, "s-idle")
    row = list_sessions()[0]
    assert row["coordination_leases"] == []


def test_active_leases_project_onto_the_holding_session(test_db):
    _insert_session(test_db, "s-holder", current_item_id="41")
    insert_item(test_db, id=41, title="claimed work")
    test_db.commit()
    _insert_item_claim(test_db, "s-holder", 41)
    _insert_lease(
        test_db,
        session_id="s-holder",
        lease_key="QA_HOST:yoke",
        owner_session_id="s-holder",
    )
    _insert_lease(
        test_db,
        session_id="s-holder",
        lease_key="LIVE_DB_MIGRATION:governed",
        owner_session_id="s-holder",
    )
    _insert_lease(
        test_db,
        session_id="s-holder",
        lease_key="QA_HOST:released",
        owner_session_id="s-holder",
        released_at=_iso(5),
    )
    _insert_lease(
        test_db,
        session_id="s-holder",
        lease_key="LIVE_DB_MIGRATION:primary",
        owner_kind="item",
        owner_item_id=41,
    )

    row = list_sessions()[0]
    keys = {lease["lease_key"] for lease in row["coordination_leases"]}
    assert keys == {
        "LIVE_DB_MIGRATION:governed",
        "LIVE_DB_MIGRATION:primary",
        "QA_HOST:yoke",
    }
    assert "QA_HOST:released" not in keys
    item_owned = next(
        lease
        for lease in row["coordination_leases"]
        if lease["lease_key"] == "LIVE_DB_MIGRATION:primary"
    )
    assert item_owned["owner_kind"] == "item"
    assert item_owned["owner_item_ref"] == "YOK-41"
    assert item_owned["owner_item_id"] == 41
    assert {lease["owner_kind"] for lease in row["coordination_leases"]} == {
        "item",
        "session",
    }


def test_item_claim_carries_public_drill_in_coordinates(test_db):
    insert_item(test_db, id=5001, project_sequence=4200, title="divergent")
    _insert_session(test_db, "s-div", current_item_id="5001")
    _insert_item_claim(test_db, "s-div", 5001)
    claim = list_sessions()[0]["claims"][0]
    assert claim["target"] == "YOK-4200"
    assert claim["item_ref"] == "YOK-4200"
    assert claim["item_project_id"] == 1
    assert claim["item_project_sequence"] == 4200


def test_item_owned_lease_stays_off_sessions_that_do_not_claim_the_item(test_db):
    insert_item(test_db, id=41, title="claimed work")
    _insert_session(test_db, "s-holder", current_item_id="41")
    _insert_session(test_db, "s-other")
    _insert_item_claim(test_db, "s-holder", 41)
    _insert_lease(
        test_db,
        session_id="s-other",
        lease_key="LIVE_DB_MIGRATION:primary",
        owner_kind="item",
        owner_item_id=41,
    )
    rows = {row["session_id"]: row for row in list_sessions()}
    holder_keys = {
        lease["lease_key"] for lease in rows["s-holder"]["coordination_leases"]
    }
    other_keys = {
        lease["lease_key"] for lease in rows["s-other"]["coordination_leases"]
    }
    assert holder_keys == {"LIVE_DB_MIGRATION:primary"}
    assert other_keys == set()


def test_claimed_blitz_worktrees_project_onto_the_holding_session(test_db):
    insert_item(test_db, id=80, workflow_id="blitz", title="blitz epic")
    worker = insert_item_worktree(
        test_db, item_id=80, branch="blitz/80-w", lane_role="worker",
    )
    integration = insert_item_worktree(
        test_db, item_id=80, branch="blitz/80-i", lane_role="integration",
    )
    insert_item_worktree(
        test_db, item_id=80, branch="blitz/80-impl", lane_role="implementation",
    )
    _insert_session(test_db, "s-blitz", current_item_id="80")
    _insert_item_claim(test_db, "s-blitz", 80)
    ids = list_sessions()[0]["claimed_blitz_worktree_ids"]
    assert sorted(ids) == sorted([int(worker["id"]), int(integration["id"])])
