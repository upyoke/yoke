"""Taking several published updates in one operator action.

The batch is exactly its entries taken individually: same merge, same
stale-version guard, one line of outcome each. What it adds is that a refusal
somewhere in the middle neither stops the rest nor hides which one it was.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.builtin_workflow_canon import canon_generations
from yoke_core.domain.handlers.workflows_canon_update import (
    handle_workflows_canon_update_apply_all,
)
from yoke_core.domain.workflow_registry import (
    list_current_workflows,
    publish_workflow_version,
)


def _apply_all(payload: dict, *, target_kind: str = "global"):
    target = (
        TargetRef(kind="global") if target_kind == "global"
        else TargetRef(kind="item", item_id=1)
    )
    return handle_workflows_canon_update_apply_all(
        FunctionCallRequest(
            function="workflows.canon_update.apply_all",
            actor=ActorContext(actor_id="1", session_id=""),
            target=target,
            payload=payload,
        ),
    )


def _workflow(conn, workflow_id: str) -> dict:
    return next(
        row for row in list_current_workflows(conn) if row["id"] == workflow_id
    )


def _entry(conn, workflow_id: str, *, expected: int | None = None) -> dict:
    """One batch entry naming the version this caller believes is current."""
    return {
        "workflow_id": workflow_id,
        "expected_current_version": (
            int(_workflow(conn, workflow_id)["current_version"])
            if expected is None else expected
        ),
    }


def _fall_behind(conn, *workflow_ids: str) -> None:
    """Put each named workflow on a generation that is not the newest."""
    for workflow_id in workflow_ids:
        older = canon_generations(workflow_id)[-2]
        publish_workflow_version(
            conn, workflow_id=workflow_id, definition=dict(older.definition),
        )


def test_several_behind_workflows_are_all_brought_current(test_db):
    _fall_behind(test_db, "issue", "epic")
    entries = [_entry(test_db, "issue"), _entry(test_db, "epic")]

    outcome = _apply_all({"workflows": entries})

    assert outcome.primary_success
    result = outcome.result_payload
    assert result["refused"] == []
    assert {row["workflow_id"] for row in result["applied"]} == {"issue", "epic"}
    for workflow_id in ("issue", "epic"):
        assert (
            _workflow(test_db, workflow_id)["canon_status"]["state"]
            == "up_to_date"
        )


def test_one_refusal_neither_stops_the_others_nor_hides_itself(test_db):
    """A stale entry refuses on its own terms; its neighbour still moves."""
    _fall_behind(test_db, "issue", "epic")
    entries = [
        _entry(test_db, "issue", expected=999),
        _entry(test_db, "epic"),
    ]

    outcome = _apply_all({"workflows": entries})

    assert outcome.primary_success
    result = outcome.result_payload
    assert [row["workflow_id"] for row in result["applied"]] == ["epic"]
    assert [row["workflow_id"] for row in result["refused"]] == ["issue"]
    assert result["refused"][0]["code"] == "incompatible"
    assert "refresh first" in result["refused"][0]["message"]
    assert (
        _workflow(test_db, "epic")["canon_status"]["state"] == "up_to_date"
    )
    assert (
        _workflow(test_db, "issue")["canon_status"]["state"]
        == "update_available"
    )


def test_an_up_to_date_workflow_is_reported_rather_than_silently_skipped(
    test_db,
):
    outcome = _apply_all({"workflows": [_entry(test_db, "issue")]})

    assert outcome.primary_success
    result = outcome.result_payload
    assert result["applied"] == []
    assert result["refused"][0]["workflow_id"] == "issue"
    assert "already up to date" in result["refused"][0]["message"]


def test_refusing_everything_is_still_a_successful_report(test_db):
    """An error envelope would discard the per-entry reasons that are the
    answer."""
    outcome = _apply_all({"workflows": [_entry(test_db, "issue")]})

    assert outcome.primary_success
    assert outcome.error is None
    assert len(outcome.result_payload["refused"]) == 1


def test_naming_a_workflow_twice_is_refused_rather_than_racing_itself(test_db):
    """The second entry would carry the version the first just moved off."""
    _fall_behind(test_db, "issue")
    entry = _entry(test_db, "issue")

    outcome = _apply_all({"workflows": [entry, dict(entry)]})

    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "issue" in outcome.error.message


def test_an_empty_batch_is_refused(test_db):
    outcome = _apply_all({"workflows": []})

    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"


def test_the_batch_requires_a_global_target(test_db):
    outcome = _apply_all(
        {"workflows": [_entry(test_db, "issue")]}, target_kind="item",
    )

    assert not outcome.primary_success
    assert outcome.error.code == "target_invalid"
