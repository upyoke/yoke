"""The post-deploy QA question is reported the same way on every early surface."""

from __future__ import annotations

from yoke_core.domain import post_deploy_qa_obligation as obligation
from yoke_core.domain import qa_item_stage_plan_gate as plan_gate
from yoke_core.domain.post_deploy_verification_answer import (
    ANSWERED,
    UNANSWERED,
    PostDeployAnswer,
)

ITEM_SCOPED_QA = [{"name": "item-qa", "stage_kind": "qa", "scope": "item"}]
RUN_SCOPED_QA = [{"name": "run-qa", "stage_kind": "qa", "scope": "run"}]


def _obligation(stages, answer: str) -> obligation.PostDeployObligation:
    return obligation.obligation(
        public_ref="ITEM-7",
        project="yoke",
        flow_id="release-qa",
        stages=stages,
        answer=PostDeployAnswer(answer),
        transition="release",
    )


def test_an_unanswered_item_scoped_flow_names_both_answers() -> None:
    result = _obligation(ITEM_SCOPED_QA, UNANSWERED)

    assert result.unanswered
    payload = result.as_payload()
    assert payload["status"] == "unanswered"
    assert payload["flow_id"] == "release-qa"
    assert payload["answer_with"] == [
        "yoke qa item-plan attach --item ITEM-7 --project yoke --plan-id <id> "
        "--transition release --qa-phase post_deploy",
        "yoke qa post-deploy record-no-obligation --item ITEM-7 "
        '--reason "why nothing about this item is observable once deployed"',
    ]
    assert payload["summary"].startswith("unanswered (delivery flow 'release-qa'")


def test_an_answered_item_reports_its_answer_alone() -> None:
    result = _obligation(ITEM_SCOPED_QA, ANSWERED)

    assert result.summary() == "answered"
    assert "answer_with" not in result.as_payload()


def test_a_flow_without_item_scoped_qa_owes_nothing() -> None:
    assert _obligation(RUN_SCOPED_QA, UNANSWERED).summary() == "not owed"
    assert (
        obligation.obligation(
            public_ref="ITEM-7",
            project="yoke",
            flow_id="",
            stages=ITEM_SCOPED_QA,
            answer=PostDeployAnswer(UNANSWERED),
            transition="release",
        ).status
        == obligation.NOT_OWED
    )


def _detail(**overrides) -> dict:
    item = {
        "public_ref": "ITEM-7",
        "project": {"slug": "yoke"},
        "completion_flow": "release-qa",
        "qa_requirements": [],
        "qa_plan_attachments": [],
    }
    item.update(overrides)
    return item


def test_item_detail_reads_the_flow_and_the_answer(monkeypatch) -> None:
    monkeypatch.setattr(plan_gate, "flow_stages", lambda _flow: (ITEM_SCOPED_QA, ""))
    monkeypatch.setattr(plan_gate, "attachment_transition", lambda _item: "release")

    assert obligation.obligation_from_detail(_detail()).unanswered
    recorded = _detail(
        qa_requirements=[
            {"qa_phase": "post_deploy", "qa_kind": "post_deploy_no_obligation"}
        ]
    )
    assert obligation.obligation_from_detail(recorded).summary() == "no obligation"


def test_unreadable_flow_stages_report_nothing_rather_than_a_guess(monkeypatch) -> None:
    monkeypatch.setattr(plan_gate, "flow_stages", lambda _flow: (None, "read failed"))

    assert obligation.obligation_from_detail(_detail()) is None
