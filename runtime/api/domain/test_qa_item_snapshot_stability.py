"""Item gates retain snapshots; only explicit refresh applies plan edits."""

import pytest

from runtime.api.domain.test_qa_plan_case_currency import _case, _materialized
from runtime.api.test_qa_case_environment_obligations import _setup
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_plan_rematerialize import rematerialize_for_item


def _rows(conn, item_id):
    return [dict(row) for row in conn.execute(
        "SELECT * FROM qa_requirements WHERE item_id=%s ORDER BY id", (item_id,)
    ).fetchall()]


def _waive(conn, requirement_id, source):
    conn.execute(
        "UPDATE qa_requirements SET waived_at='2026-10-24T00:00:00Z', "
        "waiver_rationale='Proof intentionally waived', waiver_source=%s WHERE id=%s",
        (source, requirement_id),
    )
    conn.commit()


@pytest.mark.parametrize("cases", [
    [_case(instructions="Changed instructions")],
    [_case(), _case(case_key="added", position=2)],
    [_case(case_key="replacement")],
    [_case(method_id="machine-state-check", host_baselines=["fresh-host"],
           method_config={"assertions": [{"argv": ["/usr/bin/true"]}]})],
])
def test_gate_materialization_leaves_every_snapshot_field_unchanged(test_db, cases):
    item_id = 8617
    plan_id, requirement_id = _materialized(test_db, item_id=item_id)
    _waive(test_db, requirement_id, "operator")
    before = _rows(test_db, item_id)
    replace_plan_cases(test_db, plan_id=plan_id, cases=cases)

    result = materialize_for_item(
        test_db, item_id=item_id, transition_id="implemented"
    )

    assert result["created_requirement_ids"] == []
    assert result["existing_requirement_ids"] == [requirement_id]
    assert _rows(test_db, item_id) == before


def test_environment_relabel_cannot_split_a_waived_snapshot_at_a_gate(test_db):
    item, plan, case = _setup(test_db)
    replace_plan_cases(test_db, plan_id=plan["id"], cases=[{
        **case, "target_envs": ["prod"], "stage_reason": None,
    }])
    result = materialize_for_item(
        test_db, item_id=item["id"], transition_id="release"
    )
    requirement_id = result["created_requirement_ids"][0]
    _waive(test_db, requirement_id, "operator")
    before = _rows(test_db, item["id"])
    replace_plan_cases(test_db, plan_id=plan["id"], cases=[{
        **case, "target_envs": [], "stage_reason": None,
    }])

    again = materialize_for_item(
        test_db, item_id=item["id"], transition_id="release"
    )

    assert again["created_requirement_ids"] == []
    assert _rows(test_db, item["id"]) == before
    refreshed = rematerialize_for_item(
        test_db, item_id=item["id"], transition_id="release"
    )
    assert len(refreshed["created_requirement_ids"]) == 1
    old, new = _rows(test_db, item["id"])
    assert old == before[0]
    assert new["target_env"] is None


@pytest.mark.parametrize("source", ["operator", "system"])
def test_explicit_refresh_applies_edits_and_clears_only_system_waivers(test_db, source):
    item_id = 8618
    plan_id, requirement_id = _materialized(test_db, item_id=item_id)
    _waive(test_db, requirement_id, source)
    before = _rows(test_db, item_id)[0]
    replace_plan_cases(test_db, plan_id=plan_id, cases=[_case(instructions="Corrected")])

    refreshed = rematerialize_for_item(
        test_db, item_id=item_id, transition_id="implemented"
    )

    assert refreshed["refreshed_requirement_ids"] == [requirement_id]
    row = _rows(test_db, item_id)[0]
    assert row["instructions"] == "Corrected"
    for field in ("waived_at", "waiver_rationale", "waiver_source"):
        assert row[field] == (before[field] if source == "operator" else None)


def test_a_plan_attached_later_gets_its_own_snapshot(test_db):
    item_id = 8619
    plan_id, requirement_id = _materialized(test_db, item_id=item_id)
    before = _rows(test_db, item_id)[0]
    replace_plan_cases(test_db, plan_id=plan_id, cases=[_case(case_key="changed")])
    plan = create_plan(test_db, project="yoke", slug="later", name="Later plan")
    replace_plan_cases(test_db, plan_id=plan["id"], cases=[_case()])
    attach_plan_to_item(
        test_db, plan_id=plan["id"], item_id=item_id, transition_id="implemented"
    )

    result = materialize_for_item(
        test_db, item_id=item_id, transition_id="implemented"
    )

    assert result["existing_requirement_ids"] == [requirement_id]
    assert len(result["created_requirement_ids"]) == 1
    old, new = _rows(test_db, item_id)
    assert old == before
    assert new["plan_id"] == plan["id"]
