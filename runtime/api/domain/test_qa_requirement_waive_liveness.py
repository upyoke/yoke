"""A waiver refuses a requirement that no longer counts and names its copy.

A retracted or superseded row is already settled, so waiving it would report
success while changing nothing; the refusal sends the operator to the live
copy instead. A live requirement still waives.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import create_smoke_plan
from yoke_core.domain.qa_plan_attachment_retract import retract_requirements
from yoke_core.domain.qa_requirement_ops import waive_requirement
from yoke_core.domain.qa_requirement_waive_liveness import (
    NOT_LIVE_CODE,
    RequirementNotLiveError,
)


def _requirement(conn, *, item_id: int, slug: str) -> int:
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.qa_plan_attachments import (
        attach_plan_to_item,
        materialize_for_item,
    )

    insert_item(
        conn, id=item_id, project_sequence=item_id, workflow_id="dash", status="release"
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
    return int(created["created_requirement_ids"][0])


def _copy(conn, requirement_id: int) -> int:
    """A later live copy of the same case, as the next materialization makes."""
    columns = [
        row["column_name"]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='qa_requirements' AND column_name<>'id' "
            "ORDER BY ordinal_position"
        ).fetchall()
    ]
    names = ", ".join(columns)
    # The next materialization belongs to a later transition, which is what
    # keeps it distinct under the one-copy-per-transition identity.
    selected = ", ".join(
        "'release-again'"
        if name == "workflow_transition_id"
        else "NULL"
        if name.startswith("retract")
        else name
        for name in columns
    )
    row = conn.execute(
        f"INSERT INTO qa_requirements ({names}) SELECT {selected} FROM "
        "qa_requirements WHERE id=%s RETURNING id",
        (requirement_id,),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def _waive(conn, requirement_id: int) -> None:
    waive_requirement(
        conn, requirement_id, "operator accepted risk", source="operator", force=True
    )


def test_waiving_a_retracted_requirement_names_its_live_copy(test_db) -> None:
    requirement_id = _requirement(test_db, item_id=9871, slug="waive-retracted")
    retract_requirements(
        test_db, [requirement_id], reason="removed from run", source="operator"
    )
    test_db.commit()
    live_copy = _copy(test_db, requirement_id)

    with pytest.raises(RequirementNotLiveError) as refused:
        _waive(test_db, requirement_id)

    message = str(refused.value)
    assert message.startswith(f"{NOT_LIVE_CODE}: requirement {requirement_id}")
    assert "was retracted (removed from run)" in message
    assert f"--requirement-id {live_copy}" in message
    row = test_db.execute(
        "SELECT waived_at FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()
    assert row["waived_at"] is None


def test_waiving_a_superseded_requirement_names_its_successor(test_db) -> None:
    requirement_id = _requirement(test_db, item_id=9872, slug="waive-superseded")
    successor = _copy(test_db, requirement_id)
    test_db.execute(
        "UPDATE qa_requirements SET superseded_by_requirement_id=%s, "
        "superseded_at=now() WHERE id=%s",
        (successor, requirement_id),
    )
    test_db.commit()

    with pytest.raises(RequirementNotLiveError, match="was superseded") as refused:
        _waive(test_db, requirement_id)

    assert f"--requirement-id {successor}" in str(refused.value)


def test_retracted_requirement_without_a_copy_says_nothing_is_left(test_db) -> None:
    requirement_id = _requirement(test_db, item_id=9873, slug="waive-no-copy")
    retract_requirements(
        test_db, [requirement_id], reason="plan withdrawn", source="operator"
    )
    test_db.commit()

    with pytest.raises(RequirementNotLiveError, match="nothing is left to waive"):
        _waive(test_db, requirement_id)


def test_live_requirement_still_waives(test_db) -> None:
    requirement_id = _requirement(test_db, item_id=9874, slug="waive-live")

    _waive(test_db, requirement_id)

    row = test_db.execute(
        "SELECT waived_at, waiver_source FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    assert row["waived_at"] is not None
    assert row["waiver_source"] == "operator"


def test_handler_refuses_by_name() -> None:
    from unittest.mock import patch

    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )
    from yoke_core.domain.handlers import qa_requirement_waive

    class _Conn:
        def close(self):
            pass

    with (
        patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()),
        patch(
            "yoke_core.domain.qa_requirement_ops.waive_requirement",
            side_effect=RequirementNotLiveError(f"{NOT_LIVE_CODE}: requirement 7 ..."),
        ),
    ):
        outcome = qa_requirement_waive.handle_qa_requirement_waive(
            FunctionCallRequest(
                function="qa.requirement.waive",
                actor=ActorContext(actor_id="op", session_id="s-1"),
                target=TargetRef(kind="qa_requirement", qa_requirement_id=7),
                payload={"rationale": "r", "source": "operator", "force": True},
            )
        )

    assert outcome.primary_success is False
    assert outcome.error.code == NOT_LIVE_CODE
