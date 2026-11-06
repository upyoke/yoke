"""Run QA draws each plan group once, keyed by group id, at any attacher count."""

from runtime.api.domain.deployment_qa_run_sharing_test_support import (
    MEMBERS as MEMBERS,
    RUN as RUN,
    _attach as _attach,
    _form_groups as _form_groups,
    _plan_id as _plan_id,
    _seed_three as _seed_three,
)


import json
from collections import Counter

from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from yoke_core.domain.deployment_qa_run_sharing import run_qa_sharing
from yoke_core.domain.deployment_run_member_presentation import removed_member_items
from yoke_core.domain.qa_activity_reads import read_activity


def _close(conn, group_id, covered):
    conn.execute(
        "UPDATE qa_requirements SET covered_item_ids=%s "
        "WHERE execution_target_json::jsonb->'deployment'->'shared_plan'->>'group_id'=%s",
        (json.dumps(sorted(covered)), group_id),
    )
    conn.commit()


def _summary(sharing):
    return [
        (
            entry["plan_id"],
            entry["group_id"],
            entry["closed"],
            entry["earlier_run_id"],
            entry["case_count"],
            entry["sharing_item_ids"],
            entry.get("pending", False),
        )
        for entry in sharing["plan_groups"]
    ]


def test_each_attached_plan_shows_pending_until_its_group_exists(test_db):
    plan_id, lone = _seed_three(test_db)
    before = run_qa_sharing(test_db, [RUN])[RUN]
    assert _summary(before) == [
        (plan_id, None, False, None, 1, list(MEMBERS), True),
        (lone, None, False, None, 1, list(MEMBERS[:2]), True),
    ]
    assert before["plan_groups"][0]["cases"][0]["case_key"] == "command-smoke"
    assert before["plan_groups"][0]["cases"][0]["pending_obligation"] is True

    assert len(_form_groups(test_db)) == 2
    after = run_qa_sharing(test_db, [RUN])[RUN]
    # One group per plan, whether three items attach it or one.
    assert _summary(after) == [
        (plan_id, f"{RUN}:1", False, None, 1, list(MEMBERS), False),
        (lone, f"{RUN}:2", False, None, 1, list(MEMBERS[:2]), False),
    ]
    assert all("cases" not in entry for entry in after["plan_groups"])
    activity = read_activity(test_db, project="yoke", deployment_run_id=RUN)
    assert activity["run_sharing"] == {RUN: after}


def test_closed_and_open_groups_of_one_plan_show_separately(test_db):
    plan_id, lone = _seed_three(test_db)
    _form_groups(test_db)
    _close(test_db, f"{RUN}:1", [MEMBERS[0]])
    _form_groups(test_db)
    entries = [
        entry
        for entry in run_qa_sharing(test_db, [RUN])[RUN]["plan_groups"]
        if entry["plan_id"] == plan_id
    ]
    assert [(e["group_id"], e["closed"], e["covered_item_ids"]) for e in entries] == [
        (f"{RUN}:1", True, [MEMBERS[0]]),
        (f"{RUN}:3", False, None),
    ]
    assert entries[0]["sharing_item_ids"] == [MEMBERS[0]]


def test_closed_group_of_an_earlier_run_is_labelled_with_that_run(test_db):
    plan_id, lone = _seed_three(test_db)
    _form_groups(test_db)
    _close(test_db, f"{RUN}:1", list(MEMBERS[:2]))
    successor = "run-plan-groups-next"
    test_db.execute("UPDATE deployment_runs SET status='failed' WHERE id=%s", (RUN,))
    _seed_three(test_db, successor, existing=True)
    test_db.execute(
        "UPDATE deployment_runs SET supersedes_run_id=%s WHERE id=%s", (RUN, successor)
    )
    test_db.commit()
    sharing = run_qa_sharing(test_db, [successor])[successor]
    assert _summary(sharing) == [
        (plan_id, f"{RUN}:1", True, RUN, 1, list(MEMBERS[:2]), False),
        (plan_id, None, False, None, 1, [MEMBERS[2]], True),
        (lone, None, False, None, 1, list(MEMBERS[:2]), True),
    ]
    # The earlier run keeps its own groups and owes nothing new.
    earlier = run_qa_sharing(test_db, [RUN])[RUN]
    assert [(e["group_id"], e["earlier_run_id"]) for e in earlier["plan_groups"]] == [
        (f"{RUN}:1", None),
        (f"{RUN}:2", None),
    ]


def test_superseded_and_retracted_rows_leave_group_counts(test_db):
    plan_id, lone = _seed_three(test_db)
    _form_groups(test_db)
    rows = {
        str(row[1]): int(row[0])
        for row in test_db.execute(
            "SELECT id,plan_id FROM qa_requirements WHERE deployment_run_id=%s "
            "AND plan_id IS NOT NULL",
            (RUN,),
        ).fetchall()
    }
    test_db.execute(
        "UPDATE qa_requirements SET superseded_by_requirement_id=id WHERE id=%s",
        (rows[str(plan_id)],),
    )
    test_db.execute(
        "UPDATE qa_requirements SET retracted_at='2026-10-17T00:00:00Z' WHERE id=%s",
        (rows[str(lone)],),
    )
    test_db.commit()
    entries = run_qa_sharing(test_db, [RUN])[RUN]["plan_groups"]
    # The retracted group is never shown or reused; its plan is owed again.
    assert [(e["plan_id"], e["group_id"], e["case_count"]) for e in entries] == [
        (plan_id, f"{RUN}:1", 0),
        (lone, None, 1),
    ]


def test_removed_member_shows_cancelled_checks_not_open_qa(test_db):
    _seed_three(test_db)
    own = insert_qa_requirement(
        test_db,
        item_id=None,
        deployment_run_id=RUN,
        deployment_member_item_id=MEMBERS[1],
        deployment_stage="item-qa",
        qa_phase="post_deploy",
        method_id="command",
    )
    test_db.execute(
        "UPDATE deployment_runs SET membership_removals=%s WHERE id=%s",
        (
            json.dumps(
                [
                    {
                        "item_id": MEMBERS[1],
                        "reason": "rides a later release",
                        "removed_at": "2026-10-17T00:00:00Z",
                    }
                ]
            ),
            RUN,
        ),
    )
    test_db.execute(
        "UPDATE qa_requirements SET retracted_at='2026-10-17T00:00:00Z' WHERE id=%s",
        (own["id"],),
    )
    test_db.execute(
        "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (RUN, MEMBERS[1]),
    )
    test_db.commit()
    sharing = run_qa_sharing(test_db, [RUN])[RUN]
    assert sharing["removed_members"] == [{"item_id": MEMBERS[1], "cancelled_count": 1}]
    assert all(MEMBERS[1] not in e["sharing_item_ids"] for e in sharing["plan_groups"])
    run = test_db.execute(
        "SELECT id,created_at,membership_removals FROM deployment_runs WHERE id=%s",
        (RUN,),
    ).fetchone()
    (entry,) = removed_member_items(test_db, [dict(run)])[RUN]
    assert entry["cancelled_check_count"] == 1


class _Counted:
    def __init__(self, conn):
        self.conn, self.queries = conn, Counter()

    def execute(self, sql, params=()):
        self.queries[sql] += 1
        return self.conn.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self.conn, name)


def test_group_rows_are_read_once_for_every_run_on_the_page(test_db):
    _seed_three(test_db)
    _form_groups(test_db)
    other = "run-plan-groups-other"
    _seed_three(test_db, other, existing=True)
    expected = run_qa_sharing(test_db, [RUN, other])
    conn = _Counted(test_db)
    assert run_qa_sharing(conn, [RUN, other]) == expected
    group_reads = [sql for sql in conn.queries if "covered_item_ids" in sql]
    assert len(group_reads) == 1 and conn.queries[group_reads[0]] == 1
    assert not any("deployment_member_item_id=%s" in sql for sql in conn.queries)
