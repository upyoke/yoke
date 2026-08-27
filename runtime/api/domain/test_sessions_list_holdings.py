"""``sessions.list`` projects every live claim and coordination lease.

Companion to the handler tests: those stay at the authored-file cap, so
the holdings projection (leases, per-claim drill-in coordinates) lives
here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.api.fixtures.backlog import insert_item, insert_item_worktree
from yoke_core.domain.sessions_list_read import list_sessions
from yoke_core.domain.work_claim_targets import (
    make_item_target,
    make_migration_serialization_target,
    make_qa_admission_target,
    make_steering_target,
)


def _iso(minutes_ago: int = 0) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _insert_session(
    conn, session_id: str, *, current_item_id: str | None = None
) -> None:
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
        "session_id, target_kind, scope, claimed_at, last_heartbeat, reason"
        ") VALUES (%s, 'item', %s, %s, %s, %s)",
        (
            session_id,
            make_item_target(item_id).scope_json(),
            _iso(),
            _iso(),
            "implementation",
        ),
    )
    conn.commit()


def _insert_steering_claim(conn, session_id: str) -> None:
    now = _iso()
    conn.execute(
        "INSERT INTO work_claims ("
        "session_id, target_kind, scope, claimed_at, last_heartbeat, reason"
        ") VALUES (%s, 'steering', %s, %s, %s, %s)",
        (
            session_id,
            make_steering_target(1).scope_json(),
            now,
            now,
            "strategy review",
        ),
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
    """Seed one shared-operation coordination claim by its operator key.

    The key decides the kind: migration territory is always item-owned,
    a physical host is always session-held.
    """
    del owner_kind, owner_session_id
    prefix, resource = lease_key.split(":", 1)
    if prefix == "LIVE_DB_MIGRATION":
        target = make_migration_serialization_target(1, resource, int(owner_item_id))
    else:
        target = make_qa_admission_target(resource)
    conn.execute(
        "INSERT INTO work_claims ("
        "session_id, target_kind, scope, claimed_at, last_heartbeat, "
        "released_at, release_reason"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            session_id,
            target.kind,
            target.scope_json(),
            _iso(),
            _iso(),
            released_at,
            "completed" if released_at else None,
        ),
    )
    conn.commit()


def test_session_row_carries_empty_leases_when_none_are_held(test_db):
    _insert_session(test_db, "s-idle")
    row = list_sessions()[0]
    assert row["coordination_claims"] == []


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
    keys = {lease["lease_key"] for lease in row["coordination_claims"]}
    assert keys == {
        "LIVE_DB_MIGRATION:primary",
        "QA_HOST:yoke",
    }
    assert "QA_HOST:released" not in keys
    item_owned = next(
        lease
        for lease in row["coordination_claims"]
        if lease["lease_key"] == "LIVE_DB_MIGRATION:primary"
    )
    assert item_owned["owner_kind"] == "item"
    assert item_owned["owner_item_ref"] == "YOK-41"
    assert item_owned["owner_item_id"] == 41
    assert {lease["owner_kind"] for lease in row["coordination_claims"]} == {
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


def test_steering_claim_carries_project_coordinates(test_db):
    _insert_session(test_db, "s-steering")
    _insert_steering_claim(test_db, "s-steering")

    claim = list_sessions()[0]["claims"][0]

    assert claim["target_kind"] == "steering"
    assert claim["target"] == "steering for project 1"
    assert claim["scope"] == {"project_id": 1}
    assert claim["project_id"] == 1


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
        lease["lease_key"] for lease in rows["s-holder"]["coordination_claims"]
    }
    other_keys = {
        lease["lease_key"] for lease in rows["s-other"]["coordination_claims"]
    }
    assert holder_keys == {"LIVE_DB_MIGRATION:primary"}
    assert other_keys == set()


def test_focus_on_an_unclaimed_item_reports_no_work_role(test_db):
    """A filed-but-unclaimed focus is attribution, so it carries no lane."""
    insert_item(test_db, id=61, title="claimed work")
    insert_item(test_db, id=62, title="filed while claimed")
    insert_item_worktree(test_db, item_id=61, branch="YOK-61")
    _insert_session(test_db, "s-filer", current_item_id="62")
    _insert_item_claim(test_db, "s-filer", 61)
    row = list_sessions()[0]
    assert row["current_item"] == "YOK-62"
    assert row["owns_current_item"] is False
    assert row["work_role"] is None
    assert [claim["target"] for claim in row["claims"]] == ["YOK-61"]


def test_claimed_focus_without_a_lane_reports_the_item_role(test_db):
    insert_item(test_db, id=63, title="claimed work")
    _insert_session(test_db, "s-owner", current_item_id="63")
    _insert_item_claim(test_db, "s-owner", 63)
    row = list_sessions()[0]
    assert row["owns_current_item"] is True
    assert row["work_role"] == "item"


def test_claimed_focus_with_an_active_lane_reports_that_lane_role(test_db):
    insert_item(test_db, id=64, title="claimed work")
    insert_item_worktree(
        test_db,
        item_id=64,
        branch="YOK-64",
        lane_role="integration",
    )
    _insert_session(test_db, "s-lane", current_item_id="64")
    _insert_item_claim(test_db, "s-lane", 64)
    row = list_sessions()[0]
    assert row["owns_current_item"] is True
    assert row["work_role"] == "integration"


def test_claimed_blitz_worktrees_project_onto_the_holding_session(test_db):
    insert_item(test_db, id=80, workflow_id="blitz", title="blitz epic")
    worker = insert_item_worktree(
        test_db,
        item_id=80,
        branch="blitz/80-w",
        lane_role="worker",
    )
    integration = insert_item_worktree(
        test_db,
        item_id=80,
        branch="blitz/80-i",
        lane_role="integration",
    )
    insert_item_worktree(
        test_db,
        item_id=80,
        branch="blitz/80-impl",
        lane_role="implementation",
    )
    _insert_session(test_db, "s-blitz", current_item_id="80")
    _insert_item_claim(test_db, "s-blitz", 80)
    ids = list_sessions()[0]["claimed_blitz_worktree_ids"]
    assert sorted(ids) == sorted([int(worker["id"]), int(integration["id"])])
