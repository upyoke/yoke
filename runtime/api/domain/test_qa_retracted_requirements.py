"""Retired QA history owes no evidence at summary or delivery close-out."""

from __future__ import annotations

import pytest

from runtime.api.domain import test_independent_member_delivery_close_out as delivery
from runtime.api.domain.test_deployment_qa_admission_execution import (
    _original_requirement,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _plan
from runtime.api.domain.test_shared_gate_settlement_atomicity import (
    _driver_holds_deploy_lock,
)
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from runtime.api.fixtures.backlog_inserts import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_member_requirements,
)
from yoke_core.domain.deployment_qa_source_obligation import unsatisfied_blocking
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.qa_browser_checkout_free_proof import _latest_qualifying_captures
from yoke_core.domain.qa_browser_evidence_check import (
    check_browser_artifact_disk,
    check_browser_evidence_present,
)
from yoke_core.domain.qa_browser_freshness_check import (
    _collect_stale_browser_requirements,
)
from yoke_core.domain.qa_gate_definitions import GateTarget, LatestCodeRef
from yoke_core.domain.qa_gate_summary import _format_text, render_gate_summary
from yoke_core.domain.qa_gates import check_done_gate

RETRACTED_AT = "2026-10-02T04:14:24Z"


def _retire(conn, requirement_id):
    conn.execute(
        "UPDATE qa_requirements SET retracted_at=%s WHERE id=%s",
        (RETRACTED_AT, requirement_id),
    )
    conn.commit()


@pytest.mark.parametrize("phase", ["verification", "post_deploy"])
def test_summary_retains_retracted_history_without_unsatisfied_counts(test_db, phase):
    item_id = 9890
    insert_item(test_db, id=item_id, workflow_id="dash", status="release")
    retired_id = insert_qa_requirement(
        test_db,
        item_id=item_id,
        qa_phase=phase,
        method_id="browser-inspection",
    )["id"]
    _retire(test_db, retired_id)
    replacement_id = insert_qa_requirement(test_db, item_id=item_id, qa_phase=phase)[
        "id"
    ]
    insert_qa_run(test_db, qa_requirement_id=replacement_id, verdict="pass")

    summary = render_gate_summary(
        GateTarget(item_id=item_id),
        str(test_db.info.dsn),
        transition_name="implemented",
    )

    assert summary["satisfied"]
    from yoke_core.domain.item_execution_status_helpers import collect_qa

    assert collect_qa(test_db, str(test_db.info.dsn), item_id)["blocking_total"] == (
        1 if phase == "verification" else 0
    )
    assert summary["blocking_unsatisfied_count"] == 0
    assert summary["browser_unsatisfied_count"] == 0
    retired = next(row for row in summary["requirements"] if row["id"] == retired_id)
    assert retired["retracted_at"] == RETRACTED_AT
    assert retired["satisfied"] and retired["human_review"] is None
    assert f"RETIRED #{retired_id}" in _format_text(summary)
    assert (
        test_db.execute(
            "SELECT waived_at FROM qa_requirements WHERE id=%s", (retired_id,)
        ).fetchone()["waived_at"]
        is None
    )


def test_browser_done_readers_ignore_retired_evidence_and_freshness(test_db):
    item_id = 9891
    insert_item(test_db, id=item_id, workflow_id="dash", status="release")
    retired_id = insert_qa_requirement(
        test_db,
        item_id=item_id,
        qa_phase="post_deploy",
        method_id="browser-check",
    )["id"]
    run_id = insert_qa_run(
        test_db,
        qa_requirement_id=retired_id,
        performed_by="browser_substrate",
        verdict="pass",
    )["id"]
    test_db.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,artifact_handle,created_at) "
        "VALUES (%s,'screenshot',%s,%s)",
        (run_id, '{"backend":"local","path":"missing-retired.png"}', RETRACTED_AT),
    )
    _retire(test_db, retired_id)
    where, params = GateTarget(item_id=item_id).where_clause()
    assert (
        check_browser_artifact_disk(
            test_db,
            where=where,
            params=params,
            name="member",
            transition_name="done",
            repo_root=None,
        )
        is None
    )
    assert (
        _collect_stale_browser_requirements(
            test_db,
            where=where,
            params=params,
            latest_code=LatestCodeRef(sha="f" * 40),
            qa_phase=None,
        )
        == []
    )
    assert (
        _latest_qualifying_captures(
            test_db,
            where=where,
            params=params,
            qa_phase=None,
        )
        == []
    )
    assert check_done_gate(GateTarget(item_id=item_id), str(test_db.info.dsn)).passed
    test_db.execute(
        "UPDATE qa_requirements SET qa_phase='verification' WHERE id=%s", (retired_id,)
    )
    test_db.commit()
    assert (
        check_browser_evidence_present(
            test_db,
            where=where,
            params=params,
            name="member",
            transition_name="reviewed-implementation",
        )
        is None
    )


def test_run_settlement_closes_retracted_source_with_accepted_replacement(
    test_db,
    monkeypatch,
):
    _isolate_status_effects(monkeypatch)
    plan_id = _plan(test_db, "replacement-close-out")
    monkeypatch.setattr(delivery, "_plan", lambda *_args: plan_id)
    run_id = "run-retracted-source-settlement"
    delivery._seed_final_run(test_db, run_id, shared_qa=True)
    member = delivery.MEMBER_A
    retired_id = _original_requirement(
        test_db, item_id=member, method_id="browser-inspection"
    )
    _retire(test_db, retired_id)
    replacement_id = _original_requirement(
        test_db, item_id=member, method_id="browser-inspection"
    )
    test_db.execute(
        "UPDATE qa_requirements SET qa_kind='plan_case',target_env='prod',"
        "workflow_transition_id='release',plan_id=%s,plan_case_key='command-smoke' "
        "WHERE id=%s",
        (plan_id, replacement_id),
    )
    snapshot = snapshot_member_requirements(
        test_db,
        run_id=run_id,
        item_id=member,
        selection_json=requirement_selection(requirement_ids=(replacement_id,)),
    )
    test_db.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=%s "
        "WHERE run_id=%s AND item_id=%s",
        (snapshot, run_id, member),
    )
    test_db.commit()
    delivery._settle(test_db, run_id=run_id, stage="item-qa", member=member)
    delivery._settle(test_db, run_id=run_id, stage="item-qa", member=delivery.MEMBER_B)
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='run-qa' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    delivery._settle(test_db, run_id=run_id, stage="run-qa", member=None)
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='complete' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    _driver_holds_deploy_lock(test_db, monkeypatch)

    assert delivery._status(test_db, member) == "release"
    assert cmd_update(run_id, "status", "succeeded") is None
    assert delivery._status(test_db, member) == "done"
    assert (
        unsatisfied_blocking(test_db, item_id=member, target_status="done").count == 0
    )
    retired = test_db.execute(
        "SELECT retracted_at,waived_at FROM qa_requirements WHERE id=%s", (retired_id,)
    ).fetchone()
    assert retired["retracted_at"] == RETRACTED_AT and retired["waived_at"] is None
    assert (
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()["status"]
        == "succeeded"
    )


def test_retired_run_cases_do_not_answer_an_empty_member(test_db):
    from yoke_core.domain.no_obligation_member_close_out import (
        satisfied_delivery_member,
    )

    run_id = "run-retired-only-unanswered"
    delivery._seed_final_run(test_db, run_id, shared_qa=False)
    retired_id = insert_qa_requirement(
        test_db,
        item_id=None,
        deployment_run_id=run_id,
        deployment_member_item_id=delivery.MEMBER_A,
        deployment_stage="item-qa",
        qa_phase="post_deploy",
    )["id"]
    _retire(test_db, retired_id)
    assert not satisfied_delivery_member(
        test_db,
        item_id=delivery.MEMBER_A,
        run_id=run_id,
    )


def test_terminal_readers_ignore_retired_pending_runs(test_db):
    from yoke_core.domain.qa_terminal_settlement import (
        _blocking_requirement_rows,
        blocking_requirement_issues,
        find_unsettled_records,
    )

    item_id = 9892
    insert_item(test_db, id=item_id, workflow_id="dash", status="release")
    retired_id = insert_qa_requirement(test_db, item_id=item_id)["id"]
    insert_qa_run(test_db, qa_requirement_id=retired_id, verdict=None)
    _retire(test_db, retired_id)
    [history] = _blocking_requirement_rows(test_db, item_id)
    assert history["retracted_at"] == RETRACTED_AT
    assert find_unsettled_records(test_db, item_id=item_id) == []
    assert (
        blocking_requirement_issues(
            [
                {
                    "id": retired_id,
                    "blocking_mode": "blocking",
                    "retracted_at": RETRACTED_AT,
                }
            ],
            accepted_shas=(),
            public_ref="member",
            require_any=True,
        )
        == []
    )
