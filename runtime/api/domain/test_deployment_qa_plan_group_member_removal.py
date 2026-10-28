"""Removing run members retracts a plan group only once no member attaches it."""

from runtime.api.domain.test_deployment_qa_plan_groups import MEMBERS, RUN, _seed
from runtime.api.domain.test_deployment_shipping_reads import CountedConnection
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_plan_groups import run_groups


def _retracted(conn, requirement_ids):
    return [
        row[0] is not None
        for row in conn.execute(
            "SELECT retracted_at FROM qa_requirements WHERE id=ANY(%s) ORDER BY id",
            (list(requirement_ids),),
        ).fetchall()
    ]


def test_removing_the_last_attaching_member_retracts_the_open_group(test_db):
    from yoke_core.domain.deployment_run_member_removal import remove_member_on

    _seed(test_db)
    created = ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    assert created

    for index, member in enumerate(MEMBERS):
        remove_member_on(test_db, RUN, member, reason="split out of the release")
        last = index == len(MEMBERS) - 1
        assert _retracted(test_db, created) == [last] * len(created)
    (group,) = run_groups(test_db, [RUN], "item-qa")
    assert group.retracted and not group.open


def test_orphan_check_reads_attachments_once_and_sees_each_removal(test_db):
    from yoke_core.domain.qa_deployment_member_removal import (
        retract_orphaned_shared_copies,
    )

    _seed(test_db)
    created = ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    conn = CountedConnection(test_db)

    for index, member in enumerate(MEMBERS):
        conn.execute(
            "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
            (RUN, member),
        )
        conn.queries.clear()
        retracted = retract_orphaned_shared_copies(
            conn, run_id=RUN, reason="member moved to a later release"
        )
        last = index == len(MEMBERS) - 1
        assert sorted(retracted) == (sorted(created) if last else [])
        # One set read of the remaining members' attachments, never one per
        # member; with no member left there is nothing to read.
        attachment_reads = sum(
            count
            for sql, count in conn.queries.items()
            if "FROM qa_plan_item_attachments" in sql
        )
        assert attachment_reads == (0 if last else 1)
