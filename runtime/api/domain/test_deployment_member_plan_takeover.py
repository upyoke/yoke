"""Member correction contracts survive takeover and the successor's first freeze."""

from runtime.api.domain.deployment_run_target_takeover_test_support import (
    OLD,
    NEW,
    PASSED,
    WAITING,
    ITEM_QA_STAGE,
    _seed_old,
    _close_passed,
    _seed_new,
    _contains,
    _take_over,
)
from runtime.api.domain.deployment_run_composition_freeze_test_support import (
    _known_carried,
)
from runtime.api.domain.deployment_qa_singleton_correction_test_support import _correct
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    create_smoke_plan,
    record_case_verdict,
)
from yoke_core.domain import deployment_run_composition_freeze as composition
from yoke_core.domain.deployment_qa_plan_ownership import _snapshot
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_frozen_plan_selection import _flow_plan
from yoke_core.domain.qa_requirement_correction_selection import (
    resolve_correction_selection,
)
from yoke_core.domain.qa_requirement_replacement import declare_replacements
from yoke_core.domain.deployment_qa_snapshot_correction import refresh_selected_cases
from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot


def _admit(conn, member, failed, plan):
    record_case_verdict(conn, failed, "fail", evidence=True)
    replacements, scopes = resolve_correction_selection(
        conn, [{"requirement_id": failed}]
    )
    result = materialize_deployment_qa_stage(
        conn,
        deployment_run_id=OLD,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=member,
        agent_plan=str(plan),
        replacement_keys={"command-smoke"},
        replacement_scopes=scopes,
        replaced_requirement_ids=frozenset({failed}),
        commit=False,
    )
    declare_replacements(
        conn,
        replacements,
        materialized_requirement_ids=result["created_requirement_ids"],
    )
    conn.commit()


def test_takeover_keeps_only_moving_members_correction_through_first_freeze(
    test_db, monkeypatch
):
    cases = _seed_old(test_db, run_qa=False)
    moving = create_smoke_plan(test_db, project="yoke", slug="moving-correction")
    _correct(test_db, moving)
    _admit(test_db, WAITING, cases[WAITING], moving)
    # A different, still-open member also admits a correction, then closes.
    # Its private plan must stay behind when only WAITING moves.
    staying = create_smoke_plan(test_db, project="yoke", slug="staying-correction")
    original = _snapshot(test_db, OLD)
    private = {
        **_plan_snapshot(test_db, staying, project_id=1),
        "stage": ITEM_QA_STAGE,
        "member_item_id": PASSED,
        "selected_by_agent": True,
    }
    import json

    original["selections"].append(private)
    test_db.execute(
        "UPDATE deployment_runs SET requirement_snapshot=%s WHERE id=%s",
        (json.dumps(original), OLD),
    )
    _close_passed(test_db)
    _seed_new(test_db)
    _contains(monkeypatch)
    assert _take_over(test_db) == OLD
    inherited = _snapshot(test_db, NEW)
    assert [s["plan"]["id"] for s in inherited["selections"]] == [moving]
    monkeypatch.setattr(
        composition, "record_carried_work", lambda conn, run: _known_carried(WAITING)
    )
    test_db.execute(
        "UPDATE deployment_flows SET takes_delivery_custody=1 WHERE id=%s",
        (f"flow-{OLD}",),
    )
    assert composition.freeze_run_composition(test_db, NEW)["frozen_at"]
    frozen = _snapshot(test_db, NEW)
    scoped = [s for s in frozen["selections"] if s.get("member_item_id")]
    assert scoped == inherited["selections"]
    subject = {
        "flow_snapshot": frozen,
        "stage": {"name": ITEM_QA_STAGE},
        "member_item_id": WAITING,
    }
    assert moving in [s["plan"]["id"] for s in _flow_plan(subject, lambda value: value)]
    subject["member_item_id"] = PASSED
    assert moving not in [
        s["plan"]["id"] for s in _flow_plan(subject, lambda value: value)
    ]
    _correct(test_db, moving, label="corrected after takeover")
    refresh_selected_cases(
        test_db,
        run_id=NEW,
        stage=ITEM_QA_STAGE,
        member=WAITING,
        plan_id=moving,
        cases=_plan_snapshot(test_db, moving, project_id=1)["cases"],
    )
    saved = [
        s for s in _snapshot(test_db, NEW)["selections"] if s.get("member_item_id")
    ]
    assert (
        saved[0]["cases"][0]["instructions"]
        == "Run the corrected after takeover member probe."
    )
