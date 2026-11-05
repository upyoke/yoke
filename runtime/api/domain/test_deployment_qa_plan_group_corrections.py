"""A corrected failed group case runs from the same plan and preserves history."""

from runtime.api.domain.deployment_qa_plan_group_execution_test_support import (
    _begin,
    _fail_case,
    _settle,
)
from runtime.api.domain.deployment_qa_plan_groups_test_support import (
    MEMBERS,
    RUN,
    SLUG,
    _seed,
)
from runtime.api.domain.deployment_qa_stage_execution_test_support import _complete_case
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_management import replace_plan_cases


def _correct(conn, plan_id):
    replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[
            {
                "case_key": "command-smoke",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the corrected group probe.",
                "expected_outcome": "The corrected probe passes.",
                "method_config": {"command": "echo repaired"},
            }
        ],
    )
    conn.commit()


def test_same_plan_retry_corrects_failed_case_and_closes_group(test_db):
    plan_id = _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    (group,) = run_groups(test_db, [RUN], "item-qa")
    failed_id = _fail_case(test_db, _begin(test_db))
    assert not _settle(test_db, group)["accepted"]
    _correct(test_db, plan_id)

    materialize_deployment_qa_stage(
        test_db, deployment_run_id=RUN, deployment_stage="item-qa", agent_plan=SLUG
    )
    execution = _begin(test_db, plan=SLUG, session="correction-qa")
    (corrected,) = execution["roster"]
    corrected_id = int(corrected["requirement_id"])
    assert corrected_id != failed_id
    row = test_db.execute(
        "SELECT method_config,replacement_requirement_id FROM qa_requirements WHERE id=%s",
        (failed_id,),
    ).fetchone()
    assert "repaired" not in str(row["method_config"])
    assert row["replacement_requirement_id"] == corrected_id
    current = test_db.execute(
        "SELECT method_config FROM qa_requirements WHERE id=%s", (corrected_id,)
    ).fetchone()
    assert "repaired" in str(current["method_config"])
    _complete_case(test_db, execution)
    (closed,) = run_groups(test_db, [RUN], "item-qa")
    assert closed.closed
    assert closed.group_id == group.group_id and closed.digest == group.digest
    assert sorted(closed.covered_item_ids) == sorted(MEMBERS)


def test_pending_case_keeps_its_pinned_content_after_plan_edit(test_db):
    plan_id = _seed(test_db)
    (original,) = ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    _correct(test_db, plan_id)
    result = materialize_deployment_qa_stage(
        test_db, deployment_run_id=RUN, deployment_stage="item-qa", agent_plan=SLUG
    )
    assert result["created_requirement_ids"] == []
    execution = _begin(test_db)
    assert [row["requirement_id"] for row in execution["roster"]] == [original]
    row = test_db.execute(
        "SELECT method_config FROM qa_requirements WHERE id=%s", (original,)
    ).fetchone()
    assert "repaired" not in str(row["method_config"])


def test_pending_group_refusal_names_a_nonempty_recovery(test_db):
    from yoke_core.domain.qa_deployment_case_content_refresh import _behind_plan_refusal

    plan_id = _seed(test_db)
    (requirement_id,) = ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    _correct(test_db, plan_id)
    refusal = _behind_plan_refusal(test_db, plan_id, [requirement_id])
    assert "plan_case_superseded" in refusal
    assert "``" not in refusal
    assert "`yoke qa requirement list`" in refusal
    assert "`yoke qa requirement supersede`" in refusal


def test_group_correction_notice_names_the_same_plan(test_db, monkeypatch):
    from yoke_core.domain import deployment_qa_correction_notice as notice

    plan_id = _seed(test_db)
    (requirement_id,) = ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    bodies = []
    monkeypatch.setattr(
        notice,
        "push_run_scoped_notice",
        lambda *a, **k: bodies.append(k["body_for_route"](None)) or "sent",
    )
    result = notice.notify_correction(
        test_db,
        result={"deployment_run_id": RUN, "deployment_stage": "item-qa"},
        replacements=[{"replacement_requirement_id": requirement_id}],
    )
    assert result["delivery"] == "sent"
    assert f"--deployment-run-id {RUN} --plan {plan_id} --stage item-qa" in bodies[0]


def test_unchanged_correction_retry_keeps_the_admitted_row(test_db):
    plan_id = _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    _fail_case(test_db, _begin(test_db))
    _correct(test_db, plan_id)
    materialize_deployment_qa_stage(
        test_db, deployment_run_id=RUN, deployment_stage="item-qa", agent_plan=SLUG
    )
    execution = _begin(test_db, session="first-correction")
    corrected_id = int(execution["roster"][0]["requirement_id"])
    # An unchanged retry keeps the admitted correction rather than reverting
    # to the original release snapshot or manufacturing another replacement.
    _fail_case(test_db, execution)
    materialize_deployment_qa_stage(
        test_db, deployment_run_id=RUN, deployment_stage="item-qa", agent_plan=SLUG
    )
    execution = _begin(test_db, session="correction-retry")
    assert [row["requirement_id"] for row in execution["roster"]] == [corrected_id]
