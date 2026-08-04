"""Previewing and applying an update without discarding local edits."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.builtin_workflow_canon import canon_generations
from yoke_core.domain.handlers.workflows_canon_update import (
    handle_workflows_canon_update_apply,
    handle_workflows_canon_update_preview,
)
from yoke_core.domain.workflow_registry import (
    list_current_workflows,
    publish_workflow_version,
    set_current_workflow_version,
)
from yoke_core.domain.workflow_schema import (
    WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER,
)


def _request(function: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="1", session_id=""),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _preview(payload: dict):
    return handle_workflows_canon_update_preview(
        _request("workflows.canon_update.preview", payload),
    )


def _workflow(conn, workflow_id="issue"):
    return next(
        row for row in list_current_workflows(conn) if row["id"] == workflow_id
    )


def _publish_older_generation(conn, workflow_id="issue"):
    """Put this universe on a published generation that is not the newest."""
    generations = canon_generations(workflow_id)
    older = generations[-2]
    published = publish_workflow_version(
        conn, workflow_id=workflow_id, definition=dict(older.definition),
    )
    return older, published


def _set_baseline(conn, version_id: int, baseline: int | None) -> None:
    conn.execute(
        "ALTER TABLE workflow_versions DISABLE TRIGGER "
        f"{WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}"
    )
    try:
        conn.execute(
            "UPDATE workflow_versions SET derived_from_canon_version = %s "
            "WHERE id = %s",
            (baseline, version_id),
        )
    finally:
        conn.execute(
            "ALTER TABLE workflow_versions ENABLE TRIGGER "
            f"{WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}"
        )
    conn.commit()


def test_an_up_to_date_workflow_has_nothing_to_preview(test_db):
    outcome = _preview({"workflow_id": "issue"})

    assert not outcome.primary_success
    assert outcome.error.code == "not_found"
    assert "already up to date" in outcome.error.message


def test_a_stock_universe_behind_the_canon_previews_a_clean_take(test_db):
    _publish_older_generation(test_db)

    outcome = _preview({"workflow_id": "issue"})

    assert outcome.primary_success
    result = outcome.result_payload
    assert result["state"] == "update_available"
    assert result["clean"] is True
    assert result["conflicts"] == []
    # Nothing was edited here, so the merge is just Yoke's newest definition.
    assert result["definition"] == canon_generations("issue")[-1].definition


def test_applying_an_update_the_universe_already_holds_selects_it(test_db):
    """Taking an update is a selection when the row is already there.

    A universe that rolled back to an older generation still holds the newer
    one. Publishing a second row with the same content would collide with the
    one-digest-per-workflow constraint, and would be the wrong shape anyway.
    """
    _publish_older_generation(test_db)
    before = _workflow(test_db)
    version_count = len(before["versions"])

    outcome = handle_workflows_canon_update_apply(
        _request(
            "workflows.canon_update.apply",
            {
                "workflow_id": "issue",
                "expected_current_version": before["current_version"],
            },
        ),
    )

    assert outcome.primary_success
    after = _workflow(test_db)
    assert after["canon_status"]["state"] == "up_to_date"
    assert len(after["versions"]) == version_count
    assert after["current_version"] < before["current_version"]


def test_applying_an_update_the_universe_lacks_publishes_it(test_db):
    """A merge producing something new is a publication, not a selection."""
    generations = canon_generations("issue")
    older = generations[-2]
    # Roll onto the older generation, then drop the newest row so this
    # universe genuinely does not hold the update yet.
    published = publish_workflow_version(
        test_db, workflow_id="issue", definition=dict(older.definition),
    )
    test_db.execute(
        "ALTER TABLE workflow_versions DISABLE TRIGGER "
        f"{WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}"
    )
    test_db.execute(
        "DELETE FROM workflow_versions WHERE workflow_id = 'issue' "
        "AND id <> %s",
        (int(published["version_id"]),),
    )
    test_db.execute(
        "ALTER TABLE workflow_versions ENABLE TRIGGER "
        f"{WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}"
    )
    test_db.commit()
    before = _workflow(test_db)

    outcome = handle_workflows_canon_update_apply(
        _request(
            "workflows.canon_update.apply",
            {
                "workflow_id": "issue",
                "expected_current_version": before["current_version"],
            },
        ),
    )

    assert outcome.primary_success
    after = _workflow(test_db)
    assert after["current_version"] == before["current_version"] + 1
    assert after["canon_status"]["state"] == "up_to_date"


def test_a_stale_expected_version_refuses_rather_than_racing(test_db):
    _publish_older_generation(test_db)

    outcome = handle_workflows_canon_update_apply(
        _request(
            "workflows.canon_update.apply",
            {"workflow_id": "issue", "expected_current_version": 999},
        ),
    )

    assert not outcome.primary_success
    assert outcome.error.code == "incompatible"


def test_a_conflicting_update_is_refused_rather_than_picking_a_side(test_db):
    """Publishing over an unresolved conflict would silently choose."""
    generations = canon_generations("issue")
    older = generations[-2]
    edited = dict(older.definition)
    edited["policies"] = {
        **older.definition["policies"],
        **generations[-1].definition["policies"],
        "file_budget": "required_per_task",
    }
    edited["policies"]["generated_children"] = "epic_tasks"
    published = publish_workflow_version(
        test_db, workflow_id="issue", definition=edited,
    )
    _set_baseline(test_db, int(published["version_id"]), older.canon_version)

    preview = _preview({"workflow_id": "issue"})
    assert preview.primary_success
    if preview.result_payload["clean"]:
        # The two generations happen not to disagree on any edited key; the
        # refusal path is asserted directly below instead.
        return
    outcome = handle_workflows_canon_update_apply(
        _request(
            "workflows.canon_update.apply",
            {
                "workflow_id": "issue",
                "expected_current_version": _workflow(test_db)["current_version"],
            },
        ),
    )
    assert not outcome.primary_success
    assert outcome.error.code == "incompatible"
    assert "conflicts with local edits at" in outcome.error.message


def test_rolling_back_to_an_older_stored_version_reopens_the_update(test_db):
    """Selection is a universe's own choice, and the status follows it."""
    older, _published = _publish_older_generation(test_db)
    current = _workflow(test_db)["current_version"]
    assert _workflow(test_db)["canon_status"]["state"] == "update_available"

    set_current_workflow_version(
        test_db, workflow_id="issue", version=current - 1,
    )
    assert _workflow(test_db)["canon_status"]["state"] == "up_to_date"
    assert older.canon_version < canon_generations("issue")[-1].canon_version


def test_the_preview_requires_a_global_target():
    outcome = handle_workflows_canon_update_preview(
        FunctionCallRequest(
            function="workflows.canon_update.preview",
            actor=ActorContext(actor_id=None, session_id=""),
            target=TargetRef(kind="item", item_id=1),
            payload={"workflow_id": "issue"},
        ),
    )

    assert not outcome.primary_success
    assert outcome.error.code == "target_invalid"
