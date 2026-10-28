"""One plan group keeps answering every member that still attaches its plan."""

from runtime.api.domain.test_deployment_qa_plan_groups import (
    MEMBERS,
    RUN,
    _pass_group,
    _seed,
)
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_qa_run_acceptance import item_qa_acceptance_blockers


def _group_blockers(conn, member):
    blockers = item_qa_acceptance_blockers(conn, run_id=RUN, item_id=member)
    return [blocker for blocker in blockers if "plan group" in blocker]


def test_withdrawing_one_attachment_keeps_the_group_for_the_other_members(test_db):
    from yoke_core.domain.qa_plan_attachment_retract import retract_plan_from_item

    plan_id = _seed(test_db)
    created = ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    withdrawn = retract_plan_from_item(
        test_db,
        item_id=MEMBERS[0],
        plan_id=plan_id,
        transition_id="release",
        reason="This member does not need this plan.",
    )
    assert not set(created) & set(withdrawn["retired_requirement_ids"])
    (group,) = run_groups(test_db, [RUN], "item-qa")
    assert group.open and sorted(group.requirement_ids) == sorted(created)
    assert not _group_blockers(test_db, MEMBERS[0])
    assert _group_blockers(test_db, MEMBERS[1])

    _pass_group(test_db)

    (group,) = run_groups(test_db, [RUN], "item-qa")
    assert group.covered_item_ids == tuple(MEMBERS[1:])
    for member in MEMBERS[1:]:
        assert item_qa_acceptance_blockers(test_db, run_id=RUN, item_id=member) == []


def test_member_verdict_read_does_not_wait_for_plan_editor(test_db):
    from runtime.api.fixtures.pg_testdb import connect_test_database

    plan_id = _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    _pass_group(test_db)
    test_db.commit()
    test_db.execute("UPDATE qa_plans SET name=name WHERE id=%s", (plan_id,))
    with connect_test_database(str(test_db.info.dbname)) as reader:
        reader.execute("SET LOCAL lock_timeout='100ms'")
        assert not item_qa_acceptance_blockers(reader, run_id=RUN, item_id=MEMBERS[1])
    test_db.rollback()
