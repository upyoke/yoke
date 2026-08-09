"""Whether a new generation arrives by itself, and who decides that.

Following is on until a universe diverges from the published canon, and the two
ways to diverge -- publishing an edit, and selecting a version that is not the
newest generation -- both turn it off. Nothing turns it back on except an
operator saying so, because a rollback the next boot silently undoes is not a
rollback.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.builtin_workflow_canon import canon_generations
from yoke_core.domain.handlers.workflows_canon_follow import (
    handle_workflows_canon_follow_set,
)
from yoke_core.domain.workflow_registry import (
    converge_builtin_workflows,
    list_current_workflows,
    publish_workflow_version,
    set_current_workflow_version,
)


def _set(workflow_id: str, follow: str, *, target_kind: str = "global"):
    target = (
        TargetRef(kind="global") if target_kind == "global"
        else TargetRef(kind="item", item_id=1)
    )
    return handle_workflows_canon_follow_set(
        FunctionCallRequest(
            function="workflows.canon_follow.set",
            actor=ActorContext(actor_id="1", session_id=""),
            target=target,
            payload={"workflow_id": workflow_id, "follow": follow},
        ),
    )


def _workflow(conn, workflow_id: str = "issue") -> dict:
    return next(
        row for row in list_current_workflows(conn) if row["id"] == workflow_id
    )


def _canon(conn, workflow_id: str = "issue") -> dict:
    return _workflow(conn, workflow_id)["canon_status"]


def _version_holding(conn, canon_version: int, workflow_id: str = "issue") -> int:
    """This universe's own number for a given published generation.

    Version numbers are sequence positions in one universe's history, so which
    row holds which generation is a question about that universe rather than
    arithmetic on the canon.
    """
    return next(
        int(row["version"])
        for row in _workflow(conn, workflow_id)["versions"]
        if row["provenance"].get("canon_version") == canon_version
    )


def _publish_older_generation(conn, workflow_id: str = "issue") -> dict:
    """Put this universe on a published generation that is not the newest."""
    older = canon_generations(workflow_id)[-2]
    return publish_workflow_version(
        conn, workflow_id=workflow_id, definition=dict(older.definition),
    )


def test_the_read_reports_following_and_the_last_automatic_adoption(test_db):
    status = _canon(test_db)

    assert status["follow"] == "auto"
    assert status["adopted_from_version"] is None


def test_a_workflow_with_no_canon_reports_no_following_setting(test_db):
    """A following setting for a workflow nothing publishes describes nothing."""
    test_db.execute(
        "UPDATE workflows SET source = 'project' WHERE id = 'issue'"
    )
    test_db.commit()

    assert _canon(test_db) == {"state": "not_applicable"}


def test_publishing_locally_stops_following(test_db):
    _publish_older_generation(test_db)

    assert _canon(test_db)["follow"] == "manual"


def test_selecting_an_older_generation_stops_following(test_db):
    """Otherwise the next boot moves it back and the rollback lasts until the
    next restart."""
    _publish_older_generation(test_db)
    generations = canon_generations("issue")
    newest = _version_holding(test_db, generations[-1].canon_version)
    older = _version_holding(test_db, generations[-2].canon_version)
    set_current_workflow_version(test_db, workflow_id="issue", version=newest)
    assert _set("issue", "auto").primary_success

    set_current_workflow_version(test_db, workflow_id="issue", version=older)

    assert _canon(test_db)["follow"] == "manual"


def test_the_stopped_rollback_survives_the_next_boot(test_db):
    """The point of stopping: convergence leaves the rolled-back universe on
    the version its operator chose."""
    _publish_older_generation(test_db)
    older = _version_holding(test_db, canon_generations("issue")[-2].canon_version)
    set_current_workflow_version(test_db, workflow_id="issue", version=older)

    converge_builtin_workflows(test_db)

    assert _workflow(test_db)["current_version"] == older


def test_selecting_the_newest_generation_keeps_following(test_db):
    """Convergence has nowhere to move a universe already on the newest
    generation, so that selection carries no divergence to record."""
    _publish_older_generation(test_db)
    newest = _version_holding(
        test_db, canon_generations("issue")[-1].canon_version
    )
    assert _set("issue", "auto").primary_success

    set_current_workflow_version(test_db, workflow_id="issue", version=newest)

    status = _canon(test_db)
    assert status["state"] == "up_to_date"
    assert status["follow"] == "auto"


def test_selecting_a_version_never_turns_following_back_on(test_db):
    """Re-enabling an automatic behavior an operator switched off is their
    call, not a side effect of picking a version."""
    _publish_older_generation(test_db)
    newest = _version_holding(
        test_db, canon_generations("issue")[-1].canon_version
    )
    assert _canon(test_db)["follow"] == "manual"

    set_current_workflow_version(test_db, workflow_id="issue", version=newest)

    assert _canon(test_db)["follow"] == "manual"


def test_selecting_a_version_clears_a_stale_adoption_notice(test_db):
    """The notice described an automatic move this selection supersedes."""
    _publish_older_generation(test_db)
    assert _set("issue", "auto").primary_success
    converge_builtin_workflows(test_db)
    adopted_from = _canon(test_db)["adopted_from_version"]
    assert adopted_from is not None, "the boot should have adopted and said so"

    set_current_workflow_version(
        test_db, workflow_id="issue", version=adopted_from,
    )

    assert _canon(test_db)["adopted_from_version"] is None


def test_turning_following_back_on_adopts_nothing_by_itself(test_db):
    """Applying a definition stays the boot convergence's job."""
    _publish_older_generation(test_db)
    before = _canon(test_db)

    outcome = _set("issue", "auto")

    assert outcome.primary_success
    after = _canon(test_db)
    assert after["follow"] == "auto"
    assert after["state"] == before["state"] == "update_available"


def test_following_again_lets_the_next_boot_take_the_update(test_db):
    _publish_older_generation(test_db)
    _set("issue", "auto")

    converge_builtin_workflows(test_db)

    assert _canon(test_db)["state"] == "up_to_date"


def test_a_workflow_without_a_canon_refuses_a_following_setting(test_db):
    test_db.execute(
        "UPDATE workflows SET source = 'project' WHERE id = 'issue'"
    )
    test_db.commit()

    outcome = _set("issue", "auto")

    assert not outcome.primary_success
    assert outcome.error.code == "incompatible"
    assert "no published canon" in outcome.error.message


def test_an_unknown_workflow_is_not_found(test_db):
    outcome = _set("nonexistent-workflow", "manual")

    assert not outcome.primary_success
    assert outcome.error.code == "not_found"


def test_an_unsupported_setting_is_refused(test_db):
    outcome = _set("issue", "sometimes")

    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"


def test_the_setting_requires_a_global_target(test_db):
    outcome = _set("issue", "auto", target_kind="item")

    assert not outcome.primary_success
    assert outcome.error.code == "target_invalid"
