"""A member owes a run only the post-deploy cases that run at its environment.

In-process: the plan and run reads are stubbed so each test pins the one
decision, from case ``target_envs``, that both ownership and the member
answer share.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import deployment_qa_member_plans as member_plans
from yoke_core.domain import deployment_qa_plan_ownership as ownership
from yoke_core.domain import deployment_qa_snapshot_selection as selection
from yoke_core.domain import post_deploy_verification_answer as answers
from yoke_core.domain import qa_plan_case_definition as case_definition
from yoke_core.domain.post_deploy_verification_answer import (
    ANSWERED,
    NOT_REQUIRED,
    OTHER_ENVIRONMENT_REASON,
    PostDeployAnswer,
    member_post_deploy_answer,
)


def _case(key: str, envs: list[str]) -> dict:
    return {"case_key": key, "target_envs": json.dumps(envs)}


class _Conn:
    """Answers the cross-project environment-name lookup: the plan's env is prod."""

    def execute(self, sql, params=()):
        class _Row:
            def fetchone(self):
                return ("prod",)

        return _Row()


PROD_RUN = (6, 1, "prod")
STAGE_RUN = (5, 1, "stage")
# A plan of another project bound to its own "prod", as PLAT-419's was.
PLAN_ROW = {"item_id": 7, "plan_id": 19, "project_id": 3, "target_environment_id": 3}


def _owed(monkeypatch, cases, run_target, *, attached=True) -> set[int]:
    monkeypatch.setattr(case_definition, "plan_cases", lambda conn, plan_id: cases)
    monkeypatch.setattr(selection, "plan_matches_target", lambda *a, **k: False)
    owed = member_plans._owed(_Conn(), [7], run_target, [(PLAN_ROW, attached)], {})
    return owed[7]


def test_stage_only_plan_cases_are_not_owed_on_a_prod_run(monkeypatch):
    assert _owed(monkeypatch, [_case("a", ["stage"])], PROD_RUN) == set()


def test_prod_targeted_plan_case_is_still_owed_on_a_prod_run(monkeypatch):
    cases = [_case("a", ["stage"]), _case("b", ["prod"])]
    assert _owed(monkeypatch, cases, PROD_RUN) == {19}


def test_untargeted_case_is_owed_wherever_its_plan_reaches(monkeypatch):
    assert _owed(monkeypatch, [_case("a", [])], PROD_RUN) == {19}


def test_untargeted_case_of_a_plan_bound_elsewhere_is_not_owed(monkeypatch):
    # The prod-bound plan does not reach stage; its untargeted case runs at prod.
    assert _owed(monkeypatch, [_case("a", [])], STAGE_RUN) == set()
    assert _owed(monkeypatch, [_case("a", ["stage"])], STAGE_RUN) == {19}


@pytest.mark.parametrize(
    ("envs", "name", "reaches", "owed"),
    [
        (["stage"], "prod", True, False),
        (["prod"], "prod", True, True),
        ([], "prod", True, True),
        ([], "stage", True, True),
        ([], "stage", False, False),
        (["stage"], "stage", False, True),
    ],
)
def test_cases_owed(envs, name, reaches, owed):
    assert member_plans.cases_owed([_case("a", envs)], name, reaches=reaches) is owed


def _member(monkeypatch, direct_envs, *, owed=(), attached=False):
    """Answer one prod-run member whose frozen direct cases target ``direct_envs``."""
    monkeypatch.setattr(member_plans, "run_environment_name", lambda conn, run: "prod")
    monkeypatch.setattr(
        member_plans,
        "member_plan_disposition",
        lambda conn, item, run: (set(owed), attached),
    )
    monkeypatch.setattr(ownership, "member_plan_ids", lambda conn, run, item: set())
    monkeypatch.setattr(
        answers, "answer_for_item", lambda conn, item: PostDeployAnswer(ANSWERED)
    )
    requirements = [
        {"id": n, "plan_id": None, "qa_phase": "post_deploy", "target_env": env}
        for n, env in enumerate(direct_envs, start=1)
    ]
    subject = {
        "id": "run-prod",
        "member_item_id": 7,
        "member_snapshot": {"requirements": requirements},
    }
    return member_post_deploy_answer(object(), subject)


def test_stage_only_direct_cases_are_not_required_on_a_prod_run(monkeypatch):
    answer = _member(monkeypatch, ["stage"])
    assert answer.verdict == NOT_REQUIRED
    assert answer.reasons == (OTHER_ENVIRONMENT_REASON,)
    assert answer.discharges_without_cases


def test_stage_only_plan_cases_are_not_required_on_a_prod_run(monkeypatch):
    answer = _member(monkeypatch, [], attached=True)
    assert answer.verdict == NOT_REQUIRED
    assert answer.reasons == (OTHER_ENVIRONMENT_REASON,)


def test_prod_targeted_direct_case_is_still_owed(monkeypatch):
    assert _member(monkeypatch, ["stage", "prod"]).verdict == ANSWERED


def test_untargeted_direct_case_is_owed_everywhere(monkeypatch):
    assert _member(monkeypatch, [None]).verdict == ANSWERED
