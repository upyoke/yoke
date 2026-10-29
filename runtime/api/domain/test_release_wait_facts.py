"""The two facts a release-wait close-out reads before it promises anything.

What the item owes delivery is its completion flow's item-scoped QA stages
crossed with its own post-deploy answer; whether the session can be woken is
its surface's stopped-session wake route. These pin both reads against the
inputs the close-out actually holds: the relayed item detail payload and
the session row the park's touch returns.
"""

from __future__ import annotations

import json

from yoke_core.domain import release_wait_facts as facts

ITEM_QA_STAGES = [
    {"name": "deploy", "stage_kind": "execution", "scope": "run"},
    {"name": "item-qa", "stage_kind": "qa", "scope": "item"},
]


def _item(**extra) -> dict:
    return {
        "completion_flow": "flow-a",
        "project": {"slug": "proj"},
        "qa_requirements": [],
        "qa_plan_attachments": [],
        **extra,
    }


def _stages(monkeypatch, stages, notice=""):
    monkeypatch.setattr(facts, "flow_stages", lambda _flow: (stages, notice))


def _post_deploy(row_id: int, **extra) -> dict:
    return {"id": row_id, "qa_phase": "post_deploy", "qa_kind": "plan_case", **extra}


def test_an_answered_item_owes_its_item_scoped_stage(monkeypatch):
    _stages(monkeypatch, ITEM_QA_STAGES)
    item = _item(
        qa_requirements=[
            _post_deploy(41),
            _post_deploy(42, retracted_at="2026-01-01T00:00:00Z"),
            _post_deploy(43, waived_at="2026-01-01T00:00:00Z"),
        ]
    )

    assert facts.delivery_obligation(item) == {
        "kind": facts.OWES_QA,
        "flow": "flow-a",
        "project": "proj",
        "stages": ["item-qa"],
        "requirement_ids": [41],
        "plan_ids": [],
    }


def _attachment(plan_id: int, **extra) -> dict:
    return {"plan_id": plan_id, "qa_phase": "post_deploy", "transition_id": "release", **extra}


def test_attached_plans_are_listed_and_old_plan_copies_owe_nothing(monkeypatch):
    _stages(monkeypatch, ITEM_QA_STAGES)
    item = _item(
        qa_requirements=[_post_deploy(41), _post_deploy(44, plan_id=7)],
        qa_plan_attachments=[
            _attachment(9),
            _attachment(7),
            _attachment(8, retracted_at="2026-01-01T00:00:00Z"),
            _attachment(6, qa_phase="verification"),
        ],
    )

    obligation = facts.delivery_obligation(item)

    assert obligation["requirement_ids"] == [41]
    assert obligation["plan_ids"] == [7, 9]
    owes = facts.awaiting_delivery_lines(
        {"release_wait": {"obligation": obligation, "wake": {"kind": facts.WAKE_NATIVE}}},
        "YOK-1",
    )[0]
    assert owes == (
        "owes delivery: item-scoped QA stage item-qa (requirements 41); the stage "
        f"credits only {facts.stage_recipe(obligation, 'YOK-1')}; attached post-deploy "
        "plans 7, 9 run once per release as plan groups; the run's driver or "
        "starting session runs its plan groups"
    )


def test_a_plan_only_item_leaves_its_plan_groups_to_the_run_driver(monkeypatch):
    _stages(monkeypatch, ITEM_QA_STAGES)
    obligation = facts.delivery_obligation(_item(qa_plan_attachments=[_attachment(7)]))

    assert facts.plan_only(obligation)
    lines = facts.awaiting_delivery_lines(
        {"release_wait": {"obligation": obligation, "wake": {"kind": facts.WAKE_NATIVE}}},
        "YOK-1",
    )
    assert lines[0] == (
        "owes delivery: no item cases at item-scoped QA stage item-qa; attached "
        "post-deploy plans 7 run once per release as plan groups; the run's driver "
        "or starting session runs its plan groups"
    )
    assert (
        "re-entry runs nothing for plan groups: no wake comes to this session for them"
        in lines
    )
    assert not any("yoke watch qa-plan" in line for line in lines)


def test_a_recorded_no_obligation_owes_nothing(monkeypatch):
    _stages(monkeypatch, ITEM_QA_STAGES)
    item = _item(
        qa_requirements=[_post_deploy(50, qa_kind="post_deploy_no_obligation")]
    )

    obligation = facts.delivery_obligation(item)

    assert obligation["kind"] == facts.OWES_NOTHING
    assert "no_obligation" in obligation["detail"]


def test_a_flow_without_an_item_scoped_stage_owes_nothing(monkeypatch):
    _stages(monkeypatch, ITEM_QA_STAGES[:1])

    obligation = facts.delivery_obligation(_item())

    assert obligation == {
        "kind": facts.OWES_NOTHING,
        "detail": "flow 'flow-a' declares no item-scoped QA stage",
    }


def test_an_unreadable_flow_is_named_not_guessed(monkeypatch):
    _stages(monkeypatch, None, notice="could not read the stages")

    assert facts.delivery_obligation(_item()) == {
        "kind": facts.OWES_UNREAD,
        "detail": "could not read the stages",
    }


def test_an_item_with_no_completion_flow_is_unread():
    obligation = facts.delivery_obligation({})

    assert obligation["kind"] == facts.OWES_UNREAD


def test_a_raising_read_never_escapes(monkeypatch):
    def boom(_flow):
        raise RuntimeError("relay closed")

    monkeypatch.setattr(facts, "flow_stages", boom)

    assert facts.delivery_obligation(_item()) == {
        "kind": facts.OWES_UNREAD,
        "detail": "relay closed",
    }


def test_a_cli_surface_is_woken_natively():
    wake = facts.session_wake(
        {"executor_surface": "claude-cli", "executor_version": "2.1.287"}
    )

    assert wake == {"kind": facts.WAKE_NATIVE, "surface": "claude-cli"}


def test_a_desktop_surface_belongs_to_its_operator():
    for surface in ("claude-desktop", "codex-desktop", "cursor-desktop"):
        wake = facts.session_wake(
            {"executor_surface": surface, "executor_version": "99999.0.0"}
        )
        assert wake == {"kind": facts.WAKE_OPERATOR, "surface": surface}


def test_a_surface_with_no_stopped_route_cannot_be_woken():
    wake = facts.session_wake(
        {"executor_surface": "claude-vscode", "executor_version": "2.1.287"}
    )

    assert wake == {"kind": facts.WAKE_NONE, "surface": "claude-vscode"}


def test_no_session_row_leaves_wakeability_unread():
    assert facts.session_wake(None) == {"kind": facts.WAKE_UNREAD, "surface": ""}
    assert facts.session_wake({}) == {"kind": facts.WAKE_UNREAD, "surface": ""}


def test_json_string_flow_stages_preserve_targeted_plan_obligations(monkeypatch):
    _stages(monkeypatch, json.dumps([
        *ITEM_QA_STAGES[:1],
        {**ITEM_QA_STAGES[1], "target": {"environment": "prod"}},
    ]))
    obligation = facts.delivery_obligation(_item(qa_plan_attachments=[
        _attachment(7, target_env="prod"), _attachment(8, target_env="stage"),
    ]))
    assert obligation == {
        "kind": facts.OWES_QA, "flow": "flow-a", "project": "proj",
        "stages": ["item-qa"], "requirement_ids": [], "plan_ids": [7],
    }
