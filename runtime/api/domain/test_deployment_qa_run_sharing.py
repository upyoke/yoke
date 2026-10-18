"""Shared plans count once under Run QA; withdrawn checks leave every count."""

import json

import pytest

from runtime.api.domain.test_deployment_member_qa_copies import read
from runtime.api.domain.test_deployment_qa_shared_plans import (
    MEMBERS,
    RUN,
    _materialize,
    _seed,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _plan
from yoke_core.domain.deployment_qa_run_sharing import run_qa_sharing
from yoke_core.domain.deployment_run_member_presentation import removed_member_items
from yoke_core.domain.qa_activity_reads import read_activity


def _private_plan(conn, member, slug):
    from runtime.api.domain.test_deployment_qa_shared_plans import _attach

    plan_id = _plan(conn, slug)
    _attach(conn, member, plan_id)
    return _materialize(conn, member)["created_requirement_ids"]


def _remove(conn, member, reason="rides a later release"):
    conn.execute(
        "UPDATE deployment_runs SET membership_removals=%s WHERE id=%s",
        (
            json.dumps(
                [
                    {
                        "item_id": member,
                        "reason": reason,
                        "removed_at": "2026-10-17T00:00:00Z",
                    }
                ]
            ),
            RUN,
        ),
    )
    conn.execute(
        "UPDATE qa_requirements SET retracted_at='2026-10-17T00:00:00Z',"
        "retraction_source='operator',retraction_rationale=%s "
        "WHERE deployment_run_id=%s AND deployment_member_item_id=%s",
        (reason, RUN, member),
    )
    conn.execute(
        "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (RUN, member),
    )
    conn.commit()


def test_plan_attached_by_several_members_is_one_run_group(test_db):
    plan_id = _seed(test_db)
    shared = _materialize(test_db, MEMBERS[0])["created_requirement_ids"]
    _materialize(test_db, MEMBERS[1])
    own = _private_plan(test_db, MEMBERS[1], "member-own")
    sharing = run_qa_sharing(test_db, [RUN])[RUN]
    assert sharing["shared_plans"] == [
        {
            "plan_id": plan_id,
            "plan": "release-smoke",
            "plan_name": "Release smoke",
            "case_count": len(shared),
            "sharing_item_ids": list(MEMBERS),
        }
    ]
    projected = read(test_db, RUN, MEMBERS)
    assert projected[(RUN, MEMBERS[0])]["current"] == []
    assert [
        row["requirement_id"] for row in projected[(RUN, MEMBERS[1])]["current"]
    ] == own
    activity = read_activity(test_db, project="yoke", deployment_run_id=RUN)
    assert activity["run_sharing"] == {RUN: sharing}
    assert sorted(row["requirement_id"] for row in activity["rows"]) == sorted(
        shared + own
    )


def test_removed_member_shows_cancelled_checks_not_open_qa(test_db):
    _seed(test_db)
    _materialize(test_db, MEMBERS[0])
    own = _private_plan(test_db, MEMBERS[1], "removed-own")
    _remove(test_db, MEMBERS[1])
    sharing = run_qa_sharing(test_db, [RUN])[RUN]
    assert sharing["removed_members"] == [
        {"item_id": MEMBERS[1], "cancelled_count": len(own)}
    ]
    run = test_db.execute(
        "SELECT id,created_at,membership_removals FROM deployment_runs WHERE id=%s",
        (RUN,),
    ).fetchone()
    (entry,) = removed_member_items(test_db, [dict(run)])[RUN]
    assert entry["cancelled_check_count"] == len(own)
    # The remaining member's frozen definitions never come back as pending.
    projected = read(test_db, RUN, [MEMBERS[0]])[(RUN, MEMBERS[0])]
    assert all(not row.get("pending_obligation") for row in projected["current"])


def test_withdrawn_member_checks_leave_current_without_pending(test_db):
    _seed(test_db)
    _materialize(test_db, MEMBERS[0])
    own = _private_plan(test_db, MEMBERS[0], "superseded-own")
    test_db.execute(
        "UPDATE qa_requirements SET superseded_by_requirement_id=id WHERE id=%s",
        (own[0],),
    )
    test_db.commit()
    projected = read(test_db, RUN, [MEMBERS[0]])[(RUN, MEMBERS[0])]
    assert "error" not in projected, projected
    assert [row["requirement_id"] for row in projected["history"]] == own
    assert projected["current"] == []


def test_superseded_shared_copy_leaves_the_group_count(test_db):
    _seed(test_db)
    shared = _materialize(test_db, MEMBERS[0])["created_requirement_ids"]
    _materialize(test_db, MEMBERS[1])
    test_db.execute(
        "UPDATE qa_requirements SET superseded_by_requirement_id=id WHERE id=%s",
        (shared[0],),
    )
    test_db.commit()
    sharing = run_qa_sharing(test_db, [RUN])[RUN]
    assert [plan["case_count"] for plan in sharing["shared_plans"]] == [len(shared) - 1]
    # Still shared, so the superseded copy never falls back into a member.
    projected = read(test_db, RUN, MEMBERS)
    assert all(projected[(RUN, member)]["current"] == [] for member in MEMBERS)


@pytest.mark.parametrize("status", ["executing", "succeeded"])
def test_sharing_reuses_member_snapshot_and_attachment_sets(test_db, status):
    from runtime.api.domain.test_deployment_shipping_reads import CountedConnection
    from yoke_core.domain.deployment_qa_presentation_facts import member_presentation
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation

    _seed(test_db)
    _materialize(test_db, MEMBERS[0])
    _materialize(test_db, MEMBERS[1])
    test_db.execute("UPDATE deployment_runs SET status=%s WHERE id=%s", (status, RUN))
    test_db.commit()
    expected = run_qa_sharing(test_db, [RUN])
    conn = CountedConnection(test_db)

    @presentation_operation
    @member_presentation
    def read_shared(connection, subjects):
        return run_qa_sharing(connection, [RUN])

    subjects = [(RUN, member, "item-qa") for member in MEMBERS]
    assert read_shared(conn, subjects) == expected
    assert (
        sum(n for sql, n in conn.queries.items() if "requirement_snapshot" in sql) == 1
    )
    assert not any("ORDER BY dri.item_id" in sql for sql in conn.queries)
    assert not any("SELECT a.item_id,a.plan_id FROM" in sql for sql in conn.queries)
    # The next presentation observes changed live attachments and membership.
    _remove(test_db, MEMBERS[1])
    assert read_shared(conn, subjects) == run_qa_sharing(test_db, [RUN])
