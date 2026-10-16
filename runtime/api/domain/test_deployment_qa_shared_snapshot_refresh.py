"""Shared correction reaches existing selection owners without shadowing peers."""

import json

import pytest

from runtime.api.domain.test_deployment_qa_shared_plans import (
    MEMBERS,
    RUN,
    _materialize,
    _seed,
)
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)


def _snapshots(conn):
    return {
        int(row["item_id"]): json.loads(str(row["requirement_snapshot"]))
        for row in conn.execute(
            "SELECT item_id,requirement_snapshot FROM deployment_run_items "
            "WHERE run_id=%s ORDER BY item_id",
            (RUN,),
        ).fetchall()
    }


@pytest.mark.parametrize("both_frozen", [False, True])
def test_shared_refresh_corrects_existing_owners_without_creating_another(
    test_db,
    both_frozen,
):
    plan_id = _seed(test_db)
    (copy,) = _materialize(test_db, MEMBERS[0])["created_requirement_ids"]
    if both_frozen:
        _materialize(test_db, MEMBERS[1])
    before = _snapshots(test_db)
    flow = test_db.execute(
        "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s",
        (RUN,),
    ).fetchone()[0]
    test_db.execute(
        "UPDATE qa_plan_cases SET instructions=%s WHERE plan_id=%s",
        ("Run the corrected shared command.", plan_id),
    )
    test_db.commit()
    result = rematerialize_for_deployment_stage(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBERS[1],
    )
    assert result["refreshed_requirement_ids"] == [copy]
    after = _snapshots(test_db)
    for member in MEMBERS:
        assert len(after[member]["plans"]) == len(before[member]["plans"])
        if before[member]["plans"]:
            old = before[member]["plans"][0]
            selected = after[member]["plans"][0]
            assert selected["plan"] == old["plan"]
            assert selected["attachment"] == old["attachment"]
            assert (
                selected["cases"][0]["instructions"]
                == "Run the corrected shared command."
            )
    assert (
        test_db.execute(
            "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s",
            (RUN,),
        ).fetchone()[0]
        == flow
    )
    assert _materialize(test_db, MEMBERS[1])["existing_requirement_ids"] == [copy]
