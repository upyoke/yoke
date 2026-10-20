"""Release containment follows recorded release history, independent of time."""

from datetime import timedelta
from unittest.mock import patch

import pytest
import json

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.domain.test_release_delivery_live_visibility import (
    _open_item,
    _stage_run,
    ITEM_ID,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import item_finished_times as finished
from yoke_core.domain.item_merge_receipt_document import record_entry
from yoke_core.domain.deployment_run_containment_basis import (
    candidate_containment_basis,
)
from yoke_core.domain import deployment_run_bound_source_composition as composition
from yoke_core.domain.deployment_run_carried_work import prospective_previous_release

FINISHED = parse_instant("2026-10-17T00:00:00Z")


def _seed(conn):
    _open_item(conn)
    _stage_run(conn)
    conn.execute("UPDATE items SET status='done' WHERE id=%s", (ITEM_ID,))
    conn.execute(
        "INSERT INTO item_status_transitions(item_id,from_status,to_status,created_at) "
        "VALUES (%s,'release','done',%s)",
        (ITEM_ID, FINISHED),
    )
    conn.commit()


def _prior(
    conn,
    *,
    environment=7,
    started=FINISHED + timedelta(hours=1),
    project="yoke",
    flow="prior-flow",
):
    insert_deployment_run(
        conn,
        id="prior-" + flow,
        flow=flow,
        project=project,
        status="succeeded",
        target_environment_id=environment,
        started_at=started,
        created_at=started,
        completed_at=started + timedelta(hours=1),
    )
    conn.commit()


def _ids(basis):
    return {item["id"] for project in basis["projects"] for item in project["items"]}


def test_finished_item_does_not_age_out_of_basis_or_bound_revalidation(
    test_db, monkeypatch
):
    _seed(test_db)
    monkeypatch.setattr(
        finished, "utc_now", lambda: FINISHED + timedelta(hours=23, minutes=59)
    )
    before = candidate_containment_basis(test_db, "run-stage", bound_sources={})
    monkeypatch.setattr(finished, "utc_now", lambda: FINISHED + timedelta(hours=30))
    after = candidate_containment_basis(test_db, "run-stage", bound_sources={})
    assert before == after
    assert ITEM_ID in _ids(after)
    preview = composition.BoundSourceComposition(
        {}, None, [], {"basis_digest": before["basis_digest"]}
    )
    with patch.object(composition, "_read_composition", return_value=preview):
        assert (
            composition.revalidate_bound_source_composition(
                test_db, "run-stage", {}, frozenset(), preview
            )
            is preview
        )


@pytest.mark.parametrize("hours,expected", [(-1, True), (1, False)])
def test_latest_success_uses_its_start_as_the_finished_anchor(test_db, hours, expected):
    _seed(test_db)
    _prior(test_db, started=FINISHED + timedelta(hours=hours))
    assert (
        ITEM_ID in _ids(candidate_containment_basis(test_db, "run-stage"))
    ) is expected


@pytest.mark.parametrize("other", ["environment", "project"])
def test_another_target_or_project_cannot_clear_finished_items(test_db, other):
    _seed(test_db)
    _prior(
        test_db,
        environment=8 if other == "environment" else 9,
        project="yoke" if other == "environment" else "consumer",
    )
    assert ITEM_ID in _ids(candidate_containment_basis(test_db, "run-stage"))


def test_latest_success_not_latest_attempt_sets_anchor(test_db):
    _seed(test_db)
    _prior(test_db, started=FINISHED - timedelta(hours=1))
    _prior(test_db, flow="latest", started=FINISHED + timedelta(hours=1))
    test_db.execute(
        "UPDATE deployment_runs SET status='failed' WHERE id='prior-latest'"
    )
    assert ITEM_ID in _ids(candidate_containment_basis(test_db, "run-stage"))
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded' WHERE id='prior-latest'"
    )
    assert ITEM_ID not in _ids(candidate_containment_basis(test_db, "run-stage"))


def test_projected_takeover_and_settled_takeover_have_same_anchor(test_db):
    _seed(test_db)
    _prior(test_db)
    test_db.execute(
        "UPDATE deployment_runs SET status='executing' WHERE id='prior-prior-flow'"
    )
    with prospective_previous_release(test_db, "run-stage", "prior-prior-flow"):
        projected = candidate_containment_basis(test_db, "run-stage")
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded' WHERE id='prior-prior-flow'"
    )
    assert projected == candidate_containment_basis(test_db, "run-stage")


@pytest.mark.parametrize("hours,expected", [(-1, True), (1, False)])
def test_bound_project_finishers_share_the_carrier_release_anchor(
    test_db, hours, expected
):
    _seed(test_db)
    member = 5522
    row = insert_item(test_db, id=member, project="consumer", status="done")
    project_id = row["project_id"]
    record_entry(
        test_db,
        item_id=member,
        branch="consumer-landed",
        target="main",
        merge_sha="b" * 40,
    )
    test_db.execute(
        "INSERT INTO item_status_transitions(item_id,from_status,to_status,created_at) "
        "VALUES (%s,'release','done',%s)",
        (member, FINISHED),
    )
    test_db.execute(
        "UPDATE deployment_runs SET bound_sources=%s WHERE id='run-stage'",
        (
            json.dumps(
                {"projects": [{"project_id": project_id, "commit_sha": "c" * 40}]}
            ),
        ),
    )
    _prior(test_db, started=FINISHED + timedelta(hours=hours))
    basis = candidate_containment_basis(test_db, "run-stage")
    assert (member in _ids(basis)) is expected
