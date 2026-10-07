"""Listing where each workflow stands against its published canon."""

from __future__ import annotations

from runtime.api.workflow_version_test_helpers import publish_as_history

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.builtin_workflow_canon import canon_generations
from yoke_core.domain.handlers.workflows_canon_status import (
    handle_workflows_canon_status_list,
)


def _list(payload: dict | None = None, *, target_kind: str = "global"):
    target = (
        TargetRef(kind="global") if target_kind == "global"
        else TargetRef(kind="item", item_id=1)
    )
    return handle_workflows_canon_status_list(
        FunctionCallRequest(
            function="workflows.canon_status.list",
            actor=ActorContext(actor_id="1", session_id=""),
            target=target,
            payload=payload or {},
        ),
    )


def _rows(payload: dict | None = None) -> dict:
    outcome = _list(payload)
    assert outcome.primary_success
    return {row["workflow_id"]: row for row in outcome.result_payload["rows"]}


def test_an_up_to_date_universe_lists_its_canon_but_nothing_pending(test_db):
    rows = _rows()

    assert rows["issue"]["state"] == "up_to_date"
    assert rows["issue"]["pending"] is False
    assert rows["issue"]["follow"] == "auto"
    assert _rows({"pending_only": True}) == {}


def test_a_workflow_behind_the_canon_is_pending_with_its_current_version(test_db):
    """The row carries the version apply's stale-version guard expects."""
    older = canon_generations("issue")[-2]
    published = publish_as_history(test_db, "issue", dict(older.definition))

    pending = _rows({"pending_only": True})

    assert set(pending) == {"issue"}
    row = pending["issue"]
    assert row["state"] == "update_available"
    assert row["pending"] is True
    assert row["current_version"] == published["version"]
    assert row["current_canon_version"] == older.canon_version
    assert row["latest_canon_version"] == canon_generations("issue")[-1].canon_version


def test_a_workflow_without_a_canon_is_not_listed(test_db):
    test_db.execute(
        "UPDATE workflows SET source = 'project' WHERE id = 'issue'"
    )
    test_db.commit()

    assert "issue" not in _rows()


def test_the_list_requires_a_global_target(test_db):
    outcome = _list(target_kind="item")

    assert not outcome.primary_success
    assert outcome.error.code == "target_invalid"
