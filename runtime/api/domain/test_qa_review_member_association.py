"""A release's per-member review must stay addressable by its item.

A run-scoped check names its item in ``deployment_member_item_id``; the
schema keeps ``item_id`` null for anything run scoped. A reader that lists
what a release carries has only the item to go on, so a review whose subject
cannot name one silently vanishes from the entry it belongs to — and with it
the action a person was waiting to take.
"""

from __future__ import annotations

from runtime.api.domain.qa_review_seed import _seed_undetermined_review
from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.decision_requests import list_subject_requests
from yoke_core.domain.qa_review_requests import ensure_qa_review_request
from yoke_core.domain.qa_review_requirement_facts import (
    requirement_facts,
    review_subject,
)


def _member_requirement(conn, *, item_id: int, run_id: str, plan_id: int) -> int:
    """One release's check recorded for one member item, as the schema has it."""
    conn.execute(
        "INSERT INTO deployment_runs (id, project_id, flow, status, created_at) "
        "VALUES (%s, 1, 'yoke-hosted-stage', 'executing', '2026-07-26T00:00:00Z') "
        "ON CONFLICT (id) DO NOTHING",
        (run_id,),
    )
    requirement_id = conn.execute(
        "INSERT INTO qa_requirements "
        "(deployment_run_id, deployment_stage, deployment_member_item_id, "
        "plan_id, plan_case_key, method_id, method_name, expected_outcome, "
        "runner_id, capability_requirements, verdict_path, qa_kind, qa_phase, "
        "blocking_mode, created_at) "
        "VALUES (%s, 'release', %s, %s, 'member-smoke', 'browser-inspection', "
        "'Browser inspection', 'The release renders.', 'browser_substrate', "
        "'[\"browser-control\"]', 'agent', 'smoke', 'post_deploy', 'blocking', "
        "'2026-07-26T00:00:00Z') RETURNING id",
        (run_id, item_id, plan_id),
    ).fetchone()[0]
    conn.commit()
    return int(requirement_id)


def test_a_member_review_names_the_item_it_is_about(test_db) -> None:
    seeded = _seed_undetermined_review(
        test_db,
        item_id=4910,
        plan_slug="member-association",
        decider_roles=("owner",),
    )
    requirement_id = _member_requirement(
        test_db,
        item_id=4910,
        run_id="run-20260726-014",
        plan_id=seeded["plan_id"],
    )

    subject = review_subject(requirement_facts(test_db, requirement_id))

    # Run scoped, so `item_id` is null by construction — and the member
    # association is what makes the review addressable anyway.
    assert subject["kind"] == "deployment_run"
    assert subject["item_id"] is None
    assert subject["deployment_member_item_id"] == 4910
    assert subject["item_ref"] is not None
    assert subject["deployment_run_id"] == "run-20260726-014"


def test_a_stored_review_recovers_its_member_association_on_read(test_db) -> None:
    """A snapshot frozen before the association existed still reads with it.

    The subject travels with the live evidence refresh, so an Inbox reader
    is not left with a request it cannot place under the item it is about.
    """
    seeded = _seed_undetermined_review(
        test_db,
        item_id=4911,
        plan_slug="member-association-stored",
        decider_roles=("owner",),
    )
    requirement_id = _member_requirement(
        test_db,
        item_id=4911,
        run_id="run-20260726-015",
        plan_id=seeded["plan_id"],
    )
    run_id = test_db.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
        "created_at) VALUES (%s, 'agent', 'smoke', 'undetermined', "
        "'The release page did not settle.', '2026-07-26T00:00:00Z') "
        "RETURNING id",
        (requirement_id,),
    ).fetchone()[0]
    test_db.commit()
    request, _ = ensure_qa_review_request(
        test_db,
        requirement_id=requirement_id,
        run_id=int(run_id),
        originator_actor_id=seeded["originator"],
    )
    # Age the stored snapshot back to one written before the association was
    # recorded, which is exactly what a live universe holds.
    stored = loads_text(
        test_db.execute(
            "SELECT subject_context FROM decision_requests WHERE id=%s",
            (int(request["id"]),),
        ).fetchone()[0]
    )
    stored["subject"].pop("deployment_member_item_id", None)
    test_db.execute(
        "UPDATE decision_requests SET subject_context=%s WHERE id=%s",
        (dumps_compact(stored), int(request["id"])),
    )
    test_db.commit()

    rows = list_subject_requests(test_db, "qa_requirement", str(requirement_id))

    subject = rows[0]["subject_context"]["subject"]
    assert subject["deployment_member_item_id"] == 4911
    assert subject["deployment_run_id"] == "run-20260726-015"
