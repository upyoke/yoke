"""A landed member waiting for close-out is not reworking; a reopened one is."""

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import record_landing_receipt
from yoke_core.domain.deployment_landing_guard import reworking_members

LANDED = 9611
REOPENED = 9612
TIP = "a" * 40


def _reviewing(conn, item_id):
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id="dash",
        status="reviewing-implementation",
    )


def _enter(conn, item_id, status):
    conn.execute(
        "INSERT INTO item_status_transitions "
        "(item_id,task_num,from_status,to_status,created_at) "
        "VALUES(%s,NULL,'implementing',%s,clock_timestamp())",
        (item_id, status),
    )
    conn.commit()


def test_landing_before_closeout_keeps_member(test_db):
    _reviewing(test_db, LANDED)
    _enter(test_db, LANDED, "reviewing-implementation")
    assert reworking_members(test_db, [LANDED], reconcile=False) == {LANDED}
    record_landing_receipt(test_db, LANDED, branch="landed", tip=TIP)
    assert reworking_members(test_db, [LANDED], reconcile=False) == set()


def test_reopen_after_landing_is_still_reworking(test_db):
    _reviewing(test_db, REOPENED)
    record_landing_receipt(test_db, REOPENED, branch="reopened", tip=TIP)
    assert reworking_members(test_db, [REOPENED], reconcile=False) == set()
    _enter(test_db, REOPENED, "reviewing-implementation")
    assert reworking_members(test_db, [REOPENED], reconcile=False) == {REOPENED}
    test_db.execute(
        "UPDATE items SET status='implementing' WHERE id=%s", (REOPENED,)
    )
    _enter(test_db, REOPENED, "implementing")
    assert reworking_members(test_db, [REOPENED], reconcile=False) == {REOPENED}
