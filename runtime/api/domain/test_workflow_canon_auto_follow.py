"""Taking a newly published generation without being asked, and when not to.

A universe running an unmodified published generation has nothing to decide
about the next one, so boot convergence moves it and reports afterwards. A
universe that edited its own definition is left alone: there an update is a
merge against local work, and no automatic resolution is correct.
"""

from __future__ import annotations

from runtime.api.domain.workflow_canon_auto_follow_test_support import (
    _TS as _TS,
    _seed_generation as _seed_generation,
    _state as _state,
)


from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.workflow_registry import (
    converge_builtin_workflows,
    publish_workflow_version,
)


def test_an_unmodified_derivative_takes_the_new_generation(test_db):
    _seed_generation(test_db, "dash", 1)

    converge_builtin_workflows(test_db)

    state = _state(test_db, "dash")
    assert state["version"] > 1, "current should move onto the appended version"
    assert state["canon_adopted_from_version"] == 1
    assert state["canon_follow"] == "auto"


def test_a_second_boot_adopts_nothing_further(test_db):
    """Convergence is not a rewrite: once current is the desired version there
    is nowhere to move, and the recorded adoption is left as it stands."""
    _seed_generation(test_db, "dash", 1)
    converge_builtin_workflows(test_db)
    after_first = _state(test_db, "dash")

    converge_builtin_workflows(test_db)

    assert _state(test_db, "dash") == after_first


def test_a_local_edit_stops_following_and_keeps_its_own_version(test_db):
    """Publishing locally turns following off, so the next boot appends the new
    generation but leaves the operator's version current."""
    _seed_generation(test_db, "dash", 1)
    edited = builtin_workflow_definition("dash")["definition"]
    edited["entry_surfaces"] = [
        surface for surface in edited["entry_surfaces"] if surface != "promotion"
    ]
    # Current dash adds a "release" stage seed generation 1 never had, so the
    # structural-change guard requires an explicit mapping for every stage id
    # generation 1 carried; every one of them still exists under its own id.
    edited["stage_mapping"] = {
        "idea": "idea",
        "implementing": "implementing",
        "reviewing-implementation": "reviewing-implementation",
        "done": "done",
    }
    published = publish_workflow_version(
        test_db,
        workflow_id="dash",
        definition=edited,
        published_by_actor_id=7,
    )
    assert _state(test_db, "dash")["canon_follow"] == "manual"

    converge_builtin_workflows(test_db)

    state = _state(test_db, "dash")
    assert state["version"] == published["version"]
    assert state["canon_follow"] == "manual"
    assert state["canon_adopted_from_version"] is None


def test_a_universe_born_on_its_current_version_reports_no_adoption(test_db):
    """NULL is the honest answer for a fresh install: nothing was adopted, so
    the notice must not claim a move that never happened."""
    test_db.execute("TRUNCATE workflows, workflow_versions RESTART IDENTITY CASCADE")
    test_db.commit()

    converge_builtin_workflows(test_db)

    for workflow_id in ("dash", "issue", "epic", "blitz", "task"):
        assert _state(test_db, workflow_id)["canon_adopted_from_version"] is None
