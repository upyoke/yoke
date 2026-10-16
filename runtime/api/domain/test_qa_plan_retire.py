"""A QA plan retires only once nothing depends on it, and stays readable.

Retirement records why and by whom, refuses edits and materialization
afterwards, and refuses up front — naming each dependent with the command
that settles it — while an open requirement, a live execution or a project
default still needs the plan. Repeating it is a no-op that answers the
recorded retirement.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import create_smoke_plan
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.qa_plan_management import QaPlanError, _plan_row
from yoke_core.domain.qa_plan_retire import DEPENDENTS_CODE, retire_plan

REASON = "only case is unrunnable; its one requirement was retracted"


@contextmanager
def _handler_uses(conn):
    class _Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def close(self):
            return None

    with patch("yoke_core.domain.db_helpers.connect", return_value=_Borrowed()):
        yield


def _attached_item_requirement(
    conn, *, item_id: int, slug: str, status: str = "release"
) -> tuple[int, int]:
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.qa_plan_attachments import (
        attach_plan_to_item,
        materialize_for_item,
    )

    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id="dash",
        status="release",
    )
    conn.commit()
    plan_id = create_smoke_plan(conn, project="yoke", slug=slug)
    attach_plan_to_item(
        conn,
        plan_id=plan_id,
        item_id=item_id,
        transition_id="release",
        qa_phase="post_deploy",
    )
    created = materialize_for_item(conn, item_id=item_id, transition_id="release")
    if status != "release":
        conn.execute("UPDATE items SET status=%s WHERE id=%s", (status, item_id))
        conn.commit()
    return plan_id, int(created["created_requirement_ids"][0])


def _retire(conn, plan: int | str, reason: str = REASON, actor_id: int | None = 2):
    return retire_plan(
        conn, project="yoke", plan=str(plan), reason=reason, actor_id=actor_id
    )


def test_retire_records_reason_and_actor_and_blocks_edits(test_db) -> None:
    from yoke_core.domain.qa_plan_edit import edit_plan

    plan_id = create_smoke_plan(test_db, project="yoke", slug="retire-unused")

    result = _retire(test_db, "retire-unused")

    row = test_db.execute(
        "SELECT retired_at, retirement_reason, retired_by_actor_id FROM qa_plans "
        "WHERE id=%s",
        (plan_id,),
    ).fetchone()
    assert result["already_retired"] is False
    assert result["plan_id"] == plan_id
    assert row["retired_at"] is not None
    assert row["retirement_reason"] == REASON
    assert row["retired_by_actor_id"] == 2
    with pytest.raises(QaPlanError, match="is retired"):
        edit_plan(
            test_db,
            project="yoke",
            slug="retire-unused",
            base_updated_at="2026-01-01T00:00:00Z",
            name="renamed",
            description="",
            success_policy_id="all-pass",
            success_policy_params={},
            cases=[{}],
        )
    with pytest.raises(QaPlanError, match="is retired"):
        _plan_row(test_db, plan_id)


def test_repeat_retirement_answers_the_recorded_retirement(test_db) -> None:
    plan_id = create_smoke_plan(test_db, project="yoke", slug="retire-twice")
    first = _retire(test_db, plan_id)

    again = _retire(test_db, "retire-twice", reason="a different reason", actor_id=7)

    assert again["already_retired"] is True
    assert again["retired_at"] == first["retired_at"]
    assert again["retirement_reason"] == REASON
    assert again["retired_by_actor_id"] == 2


def test_unsettled_requirement_refuses_with_its_settling_command(test_db) -> None:
    from yoke_core.domain.qa_plan_attachment_retract import retract_plan_from_item

    plan_id, requirement_id = _attached_item_requirement(
        test_db, item_id=9861, slug="retire-open-requirement"
    )

    with pytest.raises(QaPlanError) as refused:
        _retire(test_db, plan_id)

    message = str(refused.value)
    assert message.startswith(f"{DEPENDENTS_CODE}:")
    assert f"requirement {requirement_id}" in message
    assert f"--plan-id {plan_id} --transition release" in message
    assert "yoke qa item-plan retract" in message
    retired = test_db.execute(
        "SELECT retired_at FROM qa_plans WHERE id=%s", (plan_id,)
    ).fetchone()
    assert retired["retired_at"] is None

    retract_plan_from_item(
        test_db,
        item_id=9861,
        plan_id=plan_id,
        transition_id="release",
        reason="item is done; the plan is being retired",
        source="operator",
    )
    assert _retire(test_db, plan_id)["already_retired"] is False


def test_finished_item_copies_retract_with_the_retirement(test_db) -> None:
    """A done item cannot be claimed, so its holder can never retract them."""
    plan_id, requirement_id = _attached_item_requirement(
        test_db, item_id=9863, slug="retire-finished-item", status="done"
    )

    result = _retire(test_db, plan_id)

    requirement = test_db.execute(
        "SELECT retracted_at, retraction_rationale, retraction_source "
        "FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    attachment = test_db.execute(
        "SELECT retracted_at FROM qa_plan_item_attachments WHERE item_id=%s "
        "AND plan_id=%s",
        (9863, plan_id),
    ).fetchone()
    assert result["retracted_requirement_ids"] == [requirement_id]
    assert requirement["retracted_at"] is not None
    assert requirement["retraction_rationale"] == f"QA plan retired: {REASON}"
    assert requirement["retraction_source"] == "operator"
    assert attachment["retracted_at"] is not None
    assert _retire(test_db, plan_id)["retracted_requirement_ids"] == []


def test_passed_requirement_does_not_hold_the_plan(test_db) -> None:
    plan_id, requirement_id = _attached_item_requirement(
        test_db, item_id=9862, slug="retire-passed-requirement"
    )
    test_db.execute(
        "INSERT INTO qa_runs(qa_requirement_id, performed_by, qa_kind, verdict, "
        "started_at, completed_at, created_at) VALUES (%s, 'agent', 'plan_case', "
        "'pass', '2026-09-20T00:00:00Z', '2026-09-20T00:00:01Z', "
        "'2026-09-20T00:00:00Z')",
        (requirement_id,),
    )
    test_db.commit()

    assert _retire(test_db, plan_id)["already_retired"] is False


def test_project_default_refuses_with_unset_recipe(test_db) -> None:
    plan_id = create_smoke_plan(test_db, project="yoke", slug="retire-default")
    test_db.execute(
        "INSERT INTO qa_plan_project_defaults(project_id, workflow_id, "
        "transition_id, plan_id, attached_at) VALUES "
        "(1, 'dash', 'release', %s, '2026-09-20T00:00:00Z')",
        (plan_id,),
    )
    test_db.commit()

    with pytest.raises(QaPlanError, match=DEPENDENTS_CODE) as refused:
        _retire(test_db, plan_id)

    assert (
        f"yoke qa project-default unset --project yoke --plan-id {plan_id} "
        "--workflow dash --transition release"
    ) in str(refused.value)


def test_unknown_plan_and_blank_reason_refuse_by_name(test_db) -> None:
    create_smoke_plan(test_db, project="yoke", slug="retire-reasonless")
    with pytest.raises(QaPlanError, match="qa_plan_not_found"):
        _retire(test_db, "no-such-plan")
    with pytest.raises(QaPlanError, match="qa_plan_retire_reason_required"):
        _retire(test_db, "retire-reasonless", reason="  ")


def _request(session_id: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.plan.retire",
        actor=ActorContext(actor_id="2", session_id=session_id),
        target=TargetRef(kind="global"),
        payload={"project": "yoke", "plan": "retire-handler", "reason": REASON},
    )


def test_handler_requires_a_covering_steering_seat(test_db) -> None:
    from yoke_core.domain.handlers.qa_plan_retire import handle_plan_retire

    create_smoke_plan(test_db, project="yoke", slug="retire-handler")
    with _handler_uses(test_db):
        outcome = handle_plan_retire(_request("no-seat-session"))

    assert outcome.primary_success is False
    assert outcome.error.code == "steering_seat_required"
    assert "yoke claims steering acquire --project" in outcome.error.message


def test_handler_retires_and_list_shows_retirement(test_db) -> None:
    from yoke_core.domain.handlers.qa_plan_retire import handle_plan_retire
    from yoke_core.domain.qa_plan_list_reads import list_plans

    create_smoke_plan(test_db, project="yoke", slug="retire-handler")
    with (
        _handler_uses(test_db),
        patch(
            "yoke_core.domain.session_steering_authority.require_operator_seat"
        ) as seat,
    ):
        outcome = handle_plan_retire(_request("seat-session"))

    assert outcome.primary_success is True, outcome.error
    assert outcome.result_payload["retirement_reason"] == REASON
    assert seat.call_args.kwargs["caller_session_id"] == "seat-session"
    active = [row["slug"] for row in list_plans(test_db, project="yoke")]
    listed = {
        row["slug"]: row
        for row in list_plans(test_db, project="yoke", include_retired=True)
    }
    assert "retire-handler" not in active
    assert listed["retire-handler"]["retired_at"] is not None
    assert listed["retire-handler"]["retirement_reason"] == REASON


def test_registration_declares_floor_and_seat_guardrail() -> None:
    from yoke_core.domain.handlers import _register_qa_catalog

    class _Registry:
        def __init__(self):
            self.calls = {}

        def register(self, function_id, *args, **kwargs):
            self.calls[function_id] = kwargs

    registry = _Registry()
    _register_qa_catalog.register(registry)

    kwargs = registry.calls["qa.plan.retire"]
    assert kwargs["minimum_serving_version"] == "next-release"
    assert "steering_seat_required" in kwargs["guardrails"]
