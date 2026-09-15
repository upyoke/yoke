"""The owner learns a delivery completed, once, with its destination.

Real recipient resolution and a real message insert, so a wiring defect
in the claim/session lookup would show up here. What the notice must not
do is as important as what it does: a merge-only item has no delivery to
announce, a run that failed is not one either, and nothing here is a
gate.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    _bodies,
    _claim,
    _project,
    _recipients,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_delivery_done_notice import (
    delivery_done_idempotency_key,
    notify_delivery_done,
)
from yoke_core.domain.deployment_flow_versioning import cmd_create
from yoke_core.domain.work_claim_targets import make_item_target

LINEAGE = "d" * 40


def _environment(conn: Any) -> None:
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,1,'stage','https://stage.example.test','{}',%s FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO UPDATE SET url=EXCLUDED.url",
        ("2026-09-14T00:00:00Z",),
    )


def _run(
    conn: Any,
    run_id: str,
    item_id: int,
    *,
    status: str = "succeeded",
    intent: str = "final",
    with_environment: bool = True,
    target_tier: str = "persistent",
) -> None:
    _environment(conn)
    flow_id = f"flow-{run_id}"
    cmd_create(
        conn,
        flow_id,
        "yoke",
        flow_id,
        "",
        json.dumps([{"name": "deploy", "step_runner": "auto"}]),
        status="disabled",
    )
    environment_id = (
        conn.execute(
            "SELECT id FROM environments WHERE project_id=1 AND name='stage'"
        ).fetchone()["id"]
        if with_environment
        else None
    )
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "target_tier,target_environment_id,current_stage,created_at,completed_at) "
        "VALUES (%s,1,%s,%s,%s,%s,%s,'complete',%s,%s)",
        (
            run_id,
            flow_id,
            LINEAGE,
            status,
            target_tier,
            environment_id,
            "2026-09-14T00:00:00Z",
            "2026-09-14T00:05:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at,delivery_intent) "
        "VALUES (%s,%s,%s,%s)",
        (run_id, item_id, "2026-09-14T00:00:00Z", intent),
    )
    conn.commit()


def _own(conn: Any, item_id: int) -> None:
    seed_session(conn, HOLDER_A)
    _claim(
        conn,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )


def test_owner_learns_the_destination_and_where_the_evidence_is(
    test_db: Any,
) -> None:
    _project(test_db)
    item_id = 9820
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    _run(test_db, "run-delivered", item_id)
    _own(test_db, item_id)

    result = notify_delivery_done(test_db, item_id=item_id)

    assert result["delivery"] in {"delivered", "undelivered"}
    assert result["run_id"] == "run-delivered"
    key = delivery_done_idempotency_key(item_id, "run-delivered")
    assert _recipients(test_db, key) == [HOLDER_A]
    body = _bodies(test_db, key)[0]
    assert "is done" in body
    assert "to stage" in body
    assert LINEAGE[:12] in body
    assert "run-delivered" in body
    # Informational by construction: it says so, and asks for nothing.
    assert "nothing to approve" in body


def test_a_repeat_announcement_is_one_notice(test_db: Any) -> None:
    """Existing dedupe, not a new retry framework."""
    _project(test_db)
    item_id = 9821
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    _run(test_db, "run-repeat", item_id)
    _own(test_db, item_id)

    notify_delivery_done(test_db, item_id=item_id)
    notify_delivery_done(test_db, item_id=item_id)

    key = delivery_done_idempotency_key(item_id, "run-repeat")
    assert len(_bodies(test_db, key)) == 1


def test_an_item_with_no_delivery_announces_nothing(test_db: Any) -> None:
    _project(test_db)
    item_id = 9822
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="dash")
    _own(test_db, item_id)

    result = notify_delivery_done(test_db, item_id=item_id)

    assert result == {
        "delivery": "",
        "run_id": "",
        "reason": "no succeeded deployment run is attached to this item",
    }


def test_a_failed_run_is_not_a_delivery(test_db: Any) -> None:
    _project(test_db)
    item_id = 9823
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    _run(test_db, "run-failed", item_id, status="failed")
    _own(test_db, item_id)

    assert notify_delivery_done(test_db, item_id=item_id)["delivery"] == ""


def test_a_progress_delivery_names_itself_as_one(test_db: Any) -> None:
    """A Blitz slice's run is a delivery, not the item's final completion.

    Reaching done is what triggers the notice, and a progress member does
    not reach done from the run that carried it — so the wording is the
    only thing that has to distinguish them here.
    """
    _project(test_db)
    item_id = 9824
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="blitz")
    _run(test_db, "run-progress", item_id, intent="progress")
    _own(test_db, item_id)

    notify_delivery_done(test_db, item_id=item_id)

    body = _bodies(test_db, delivery_done_idempotency_key(item_id, "run-progress"))[0]
    assert "Delivery completed" in body
    assert "Final delivery" not in body


def test_an_unnamed_destination_falls_back_to_the_target_tier(
    test_db: Any,
) -> None:
    _project(test_db)
    item_id = 9825
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    _run(
        test_db,
        "run-tierless",
        item_id,
        with_environment=False,
        target_tier="ephemeral",
    )
    _own(test_db, item_id)

    notify_delivery_done(test_db, item_id=item_id)

    body = _bodies(test_db, delivery_done_idempotency_key(item_id, "run-tierless"))[0]
    assert "to ephemeral" in body
