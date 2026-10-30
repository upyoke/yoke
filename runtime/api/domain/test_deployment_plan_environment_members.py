"""Release membership follows plans owed at each environment, with separate credit."""

import json

import pytest

from runtime.api.domain.test_deployment_qa_plan_group_credit import (
    _stage_and_prod, _misses,
)
from runtime.api.domain.test_deployment_qa_plan_groups import MEMBERS, RUN, _pass_group
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_run_member_targeting import (
    needed_member_ids, targeted_requirement_ids,
)
from yoke_core.domain.post_deploy_verification_answer import (
    NOT_REQUIRED, PLAN_GROUPS, member_post_deploy_answer, answer_for_item, ANSWERED,
)


def _target_plan(conn, plan):
    conn.execute(
        "UPDATE qa_plans SET target_environment_id=(SELECT id FROM environments "
        "WHERE project_id=1 AND name='stage') WHERE id=%s", (plan,),
    )
    conn.commit()


@pytest.mark.parametrize("alternate_names", [False, True])
def test_supplemental_plan_membership_and_completion_credit(test_db, alternate_names):
    plan = _stage_and_prod(test_db)
    _target_plan(test_db, plan)
    if alternate_names:
        test_db.execute(
            "UPDATE environments SET name=CASE name WHEN 'stage' THEN 'preview' "
            "WHEN 'prod' THEN 'live' ELSE name END WHERE project_id=1"
        )
        test_db.execute(
            "UPDATE qa_plan_cases SET target_envs='[\"preview\"]' WHERE plan_id=%s", (plan,),
        )
        test_db.commit()
    assert needed_member_ids(test_db, run_id=RUN, item_ids=MEMBERS) == frozenset(MEMBERS)
    assert targeted_requirement_ids(test_db, run_id=RUN, item_id=MEMBERS[0]) == frozenset()
    assert member_post_deploy_answer(test_db, {"id": "run-prod", "member_item_id": MEMBERS[0]}).verdict == NOT_REQUIRED
    assert answer_for_item(test_db, MEMBERS[0]).verdict == ANSWERED
    if alternate_names:
        return  # Dispatch fixtures pin their deploy receipt to the stage name.
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    assert _misses(test_db, MEMBERS[0])
    _pass_group(test_db)
    assert set(run_groups(test_db, RUN)[0].covered_item_ids) == set(MEMBERS)
    assert _misses(test_db, MEMBERS[0]) == []


def test_a_plan_with_a_case_for_the_completion_environment_owes_a_group(test_db):
    plan = _stage_and_prod(test_db)
    _target_plan(test_db, plan)
    test_db.execute(
        "UPDATE qa_plan_cases SET target_envs=%s WHERE plan_id=%s",
        (json.dumps(["stage", "prod"]), plan),
    )
    test_db.commit()
    answer = member_post_deploy_answer(test_db, {"id": "run-prod", "member_item_id": MEMBERS[0]})
    assert answer.verdict == PLAN_GROUPS


def test_plan_only_supplemental_member_survives_carried_enrollment(test_db):
    from types import SimpleNamespace
    from yoke_core.domain.deployment_run_carried_membership import enroll_carried_members
    from yoke_core.domain.deployment_run_unheld_candidates import CandidateCustody

    plan = _stage_and_prod(test_db)
    _target_plan(test_db, plan)
    test_db.execute("UPDATE items SET status='release' WHERE id=ANY(%s)", (list(MEMBERS),))
    test_db.execute("DELETE FROM deployment_run_items WHERE run_id=%s", (RUN,))
    test_db.execute(
        "UPDATE deployment_runs SET status='created',composition_frozen_at=NULL WHERE id=%s", (RUN,),
    )
    test_db.commit()
    custody = SimpleNamespace(require=lambda: CandidateCustody(enrollable=MEMBERS, held=()))
    enrolled = enroll_carried_members(
        test_db, RUN,
        carried_work={"derivation": {"contents_known": True},
                      "items": [{"item_id": member} for member in MEMBERS]},
        custody=custody,
    )
    assert len(enrolled) == len(MEMBERS)
    assert {row[0] for row in test_db.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (RUN,),
    ).fetchall()} == set(MEMBERS)


def test_unheld_candidate_filter_keeps_plan_only_supplemental_member(test_db, monkeypatch):
    from types import SimpleNamespace
    from yoke_core.domain import deployment_run_unheld_candidates as candidates
    from yoke_core.domain.deployment_run_candidate_containment import CONTAINED, ContainmentVerdict

    plan = _stage_and_prod(test_db)
    _target_plan(test_db, plan)
    monkeypatch.setattr(candidates, "merged_open_items", lambda *_: [{"id": m} for m in MEMBERS])
    monkeypatch.setattr(candidates, "items_requiring_release_membership", lambda *_: frozenset(MEMBERS))
    monkeypatch.setattr(candidates, "candidate_range_commits", lambda *a, **k: frozenset())
    monkeypatch.setattr(candidates, "_previous_release_lineage", lambda *_: "")
    monkeypatch.setattr(candidates.CandidateContainment, "contains", lambda *_: ContainmentVerdict(CONTAINED))
    monkeypatch.setattr(candidates, "landing_custody", lambda *a, **k: {
        m: SimpleNamespace(state="unheld", landing_sha="a" * 40, held=False, enrollable=True)
        for m in MEMBERS
    })
    found, held = candidates._project_custody(test_db, RUN, project_id=1, lineage="a" * 40)
    assert found == set(MEMBERS)
    assert held == []
