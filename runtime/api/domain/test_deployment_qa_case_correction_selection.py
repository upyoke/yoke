"""Correct selected keys without changing passed siblings or unrelated lineages."""

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict
from runtime.api.test_qa_plan_rematerialize_convergence import (
    MEMBER,
    _case,
    _two_case_stage,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_management import replace_plan_cases
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)
from yoke_core.domain.qa_requirement_correction_selection import (
    resolve_correction_selection,
)
from yoke_core.domain.qa_requirement_lineage import (
    head_owes_work,
    lineage_heads,
    rows_by_case,
)
from yoke_core.domain.qa_requirement_replacement import declare_replacements


@pytest.mark.parametrize("correction", ["refresh", "replaces"])
def test_passed_case_keeps_frozen_body_while_selected_failed_key_is_corrected(
    test_db, correction
):
    run = "run-selected-correction"
    plan, passed, failed = _two_case_stage(test_db, run)
    record_case_verdict(test_db, passed, "pass", evidence=True)
    record_case_verdict(test_db, failed, "fail", evidence=True)
    old = test_db.execute(
        "SELECT instructions FROM qa_requirements WHERE id=%s", (passed,)
    ).fetchone()[0]
    replace_plan_cases(
        test_db,
        plan_id=plan,
        cases=[
            _case("command-smoke", "changed passed sibling", 1),
            _case("second-smoke", "corrected failing case", 2),
        ],
    )
    scope = dict(
        deployment_run_id=run,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
    )
    if correction == "refresh":
        result = rematerialize_for_deployment_stage(test_db, **scope)
    else:
        declarations, scopes = resolve_correction_selection(
            test_db, [{"requirement_id": failed}]
        )
        result = materialize_deployment_qa_stage(
            test_db,
            **scope,
            agent_plan=str(plan),
            replacement_keys={"second-smoke"},
            replacement_scopes=scopes,
            replaced_requirement_ids=frozenset({failed}),
            commit=False,
        )
        declare_replacements(
            test_db,
            declarations,
            materialized_requirement_ids=result["created_requirement_ids"],
        )
        test_db.commit()
    assert len(result["created_requirement_ids"]) == 1
    corrected = result["created_requirement_ids"][0]
    assert (
        test_db.execute(
            "SELECT instructions FROM qa_requirements WHERE id=%s", (passed,)
        ).fetchone()[0]
        == old
    )
    assert (
        test_db.execute(
            "SELECT instructions FROM qa_requirements WHERE id=%s", (corrected,)
        ).fetchone()[0]
        == "corrected failing case"
    )
    assert (
        test_db.execute(
            "SELECT replacement_requirement_id FROM qa_requirements WHERE id=%s",
            (failed,),
        ).fetchone()[0]
        == corrected
    )


def test_lineage_scope_ignores_receipt_but_keeps_plan_baseline_and_group(test_db):
    run = "run-scope-correction"
    plan, root, _ = _two_case_stage(test_db, run)
    groups = rows_by_case(
        test_db, run_id=run, stage_name="item-qa", member_item_id=MEMBER, plan_id=plan
    )
    assert groups[("command-smoke", None)][0]["id"] == root
    # A different shared group is not this member's subject.
    assert (
        rows_by_case(
            test_db,
            run_id=run,
            stage_name="item-qa",
            member_item_id=MEMBER,
            plan_id=plan,
            group_id="other-group",
        )
        == {}
    )
    test_db.execute(
        "UPDATE qa_requirements SET retracted_at=now(),retraction_source='system' WHERE id=%s",
        (root,),
    )
    assert ("command-smoke", None) not in rows_by_case(
        test_db, run_id=run, stage_name="item-qa", member_item_id=MEMBER, plan_id=plan
    )


@pytest.mark.parametrize("verdict", ["pass", "fail", ""])
@pytest.mark.parametrize("source", ["operator", "agent", "system", None])
def test_head_work_is_decided_by_verdict_and_discharge_owner(
    monkeypatch, verdict, source
):
    from yoke_core.domain import qa_requirement_lineage as lineage

    monkeypatch.setattr(lineage, "determinate_verdict", lambda *args: verdict)
    head = dict(id=2, waived_at="now" if source else None, waiver_source=source)
    assert head_owes_work(None, head) == (
        source not in {"operator", "agent"}
        and verdict != "pass"
        and (source == "system" or verdict == "fail")
    )
    root = dict(id=1, replacement_requirement_id=2)
    assert lineage_heads([root, head], [root]) == [head]


def test_revisiting_older_content_corrects_the_failed_head_once(test_db):
    run = "run-repeat-correction-content"
    plan, root, _ = _two_case_stage(test_db, run)
    scope = dict(
        deployment_run_id=run,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
    )
    head = root
    seen = {root}
    for wording in ["first correction", "another correction", "first correction"]:
        record_case_verdict(test_db, head, "fail", evidence=True)
        replace_plan_cases(
            test_db,
            plan_id=plan,
            cases=[
                _case("command-smoke", wording, 1),
                _case("second-smoke", "run the second smoke command", 2),
            ],
        )
        result = rematerialize_for_deployment_stage(test_db, **scope)
        assert len(result["created_requirement_ids"]) == 1
        head = result["created_requirement_ids"][0]
        assert head not in seen
        seen.add(head)
        assert (
            rematerialize_for_deployment_stage(test_db, **scope)[
                "created_requirement_ids"
            ]
            == []
        )
        heads = rows_by_case(
            test_db,
            run_id=run,
            stage_name="item-qa",
            member_item_id=MEMBER,
            plan_id=plan,
        )
        assert [row["id"] for row in heads[("command-smoke", None)]] == [head]


def test_pending_correction_head_refreshes_in_place(test_db):
    run = "run-refresh-pending-head"
    plan, root, _ = _two_case_stage(test_db, run)
    scope = dict(
        deployment_run_id=run,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
    )
    record_case_verdict(test_db, root, "fail", evidence=True)
    replace_plan_cases(
        test_db, plan_id=plan, cases=[_case("command-smoke", "corrected")]
    )
    head = rematerialize_for_deployment_stage(test_db, **scope)[
        "created_requirement_ids"
    ][0]
    replace_plan_cases(
        test_db, plan_id=plan, cases=[_case("command-smoke", "corrected pending")]
    )
    result = rematerialize_for_deployment_stage(test_db, **scope)
    assert result["created_requirement_ids"] == []
    assert result["refreshed_requirement_ids"] == [head]
    assert (
        test_db.execute(
            "SELECT instructions FROM qa_requirements WHERE id=%s", (head,)
        ).fetchone()[0]
        == "corrected pending"
    )
