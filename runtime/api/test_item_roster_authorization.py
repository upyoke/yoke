"""The paged Items roster answers inside its actor's project visibility."""

from __future__ import annotations

from runtime.api.conftest import insert_item
from runtime.api.domain.handlers.items_read_test_support import (
    grant_project_viewer,
)
from runtime.api.item_roster_test_support import (
    iso_minutes_ago,
    read_roster,
    seed_ladder,
)


def test_scoped_actor_naming_no_project_sees_only_granted_projects(test_db):
    """An unscoped-looking request is still bounded by the actor's grants.

    Naming no project means "everything I may see", never "everything".
    """
    insert_item(
        test_db, id=950, title="ungranted row", project="yoke",
        status="implementing",
        created_at=iso_minutes_ago(10), updated_at=iso_minutes_ago(10),
    )
    insert_item(
        test_db, id=951, title="granted row", project="externalwebapp",
        status="implementing",
        created_at=iso_minutes_ago(11), updated_at=iso_minutes_ago(11),
    )
    test_db.commit()
    actor_id = grant_project_viewer(test_db, "externalwebapp")

    outcome = read_roster(actor_id=actor_id, page_size=50)
    assert outcome.primary_success
    titles = [row["title"] for row in outcome.result_payload["rows"]]
    assert titles == ["granted row"]
    # The total behind the page is bounded by the same grant.
    assert outcome.result_payload["match_count"] == 1


def test_scoped_actor_naming_an_ungranted_project_sees_nothing(test_db):
    insert_item(
        test_db, id=960, title="ungranted row", project="yoke",
        status="implementing",
        created_at=iso_minutes_ago(10), updated_at=iso_minutes_ago(10),
    )
    test_db.commit()
    actor_id = grant_project_viewer(test_db, "externalwebapp")

    outcome = read_roster(actor_id=actor_id, page_size=50, projects=["yoke"])
    assert outcome.primary_success
    assert outcome.result_payload["rows"] == []
    assert outcome.result_payload["match_count"] == 0


def test_unknown_project_scope_answers_empty(test_db):
    seed_ladder(test_db, 2, first_id=940)
    outcome = read_roster(page_size=5, projects=["no-such-project"])
    assert outcome.primary_success
    assert outcome.result_payload["rows"] == []
    assert outcome.result_payload["match_count"] == 0
