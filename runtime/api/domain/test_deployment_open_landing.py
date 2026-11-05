"""A delivered earlier landing cannot hide an open correction from a release."""

import pytest

from runtime.api.domain.merge_queue_observer_test_helpers import observer_connection
from yoke_core.domain.deployment_landing_guard import require_closed_landing
from yoke_core.domain.merge_queue_landing_attempt import record_attempt, close_attempt
from yoke_core.domain.deployment_run_member_admission import (
    MemberAdmission,
    admit_run_items,
)


@pytest.fixture(autouse=True)
def github_open_corrections(monkeypatch):
    from yoke_core.domain import deployment_landing_guard as guard
    from runtime.api.domain.merge_queue_observer_test_helpers import open_unarmed

    monkeypatch.setattr(guard, "read_pr_landing_state", open_unarmed)


def test_admission_refuses_an_open_unarmed_correction_before_writing_membership():
    conn = observer_connection()
    record_attempt(conn, 101, "43", enqueued_at=None)
    with pytest.raises(ValueError, match="item_landing_open:.*#43"):
        admit_run_items(conn, run_id="candidate", members=[MemberAdmission(101)])
    close_attempt(conn, 101, "43", "closed without merging")
    require_closed_landing(conn, 101)


def test_containment_refuses_an_open_correction_even_for_a_recorded_snapshot(test_db):
    import json
    from runtime.api.fixtures.backlog_inserts import insert_item
    from runtime.api.fixtures.carried_release_candidate import insert_run
    from yoke_core.domain.deployment_run_containment_basis import (
        candidate_containment_basis,
    )

    item_id = 9876
    insert_item(
        test_db,
        id=item_id,
        project_sequence=item_id,
        workflow_id="dash",
        status="release",
    )
    insert_run(
        test_db,
        "correction-candidate",
        lineage="a" * 40,
        status="created",
        flow="test-flow",
    )
    _add_member(test_db, "correction-candidate", item_id)
    record_attempt(test_db, item_id, "43", enqueued_at=None)
    test_db.execute(
        "UPDATE deployment_runs SET candidate_containment=%s WHERE id=%s",
        (
            json.dumps({"items": [{"id": item_id, "project_id": 1}]}),
            "correction-candidate",
        ),
    )
    with pytest.raises(ValueError, match="item_landing_open:.*#43"):
        candidate_containment_basis(test_db, "correction-candidate")


def _add_member(conn, run_id, item_id):
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at,requirement_snapshot) "
        "VALUES (%s,%s,%s,%s)",
        (run_id, item_id, "2026-10-20T00:00:00Z", "{}"),
    )


def _run_with_open_landings(conn, run_id, item_ids):
    from runtime.api.fixtures.backlog_inserts import insert_item
    from runtime.api.fixtures.carried_release_candidate import insert_run

    insert_run(conn, run_id, lineage="a" * 40, status="created", flow="test-flow")
    for item_id in item_ids:
        insert_item(
            conn,
            id=item_id,
            project_sequence=item_id,
            workflow_id="dash",
            status="release",
        )
        _add_member(conn, run_id, item_id)
        record_attempt(conn, item_id, str(item_id + 1000), enqueued_at=None)


def test_a_removed_member_open_correction_never_blocks_its_recorded_snapshot(test_db):
    import json
    from yoke_core.domain.deployment_run_containment_basis import (
        candidate_containment_basis,
    )
    from yoke_core.domain.deployment_run_member_removal import remove_member_on

    run_id = "removed-correction"
    _run_with_open_landings(test_db, run_id, (9876, 9877))
    items = [{"id": item_id, "project_id": 1} for item_id in (9876, 9877)]
    test_db.execute(
        "UPDATE deployment_runs SET candidate_containment=%s WHERE id=%s",
        (json.dumps({"items": items, "answers": items}), run_id),
    )
    remove_member_on(test_db, run_id, 9876, reason="rides a later release")
    with pytest.raises(ValueError, match="item_landing_open:.*#10877") as refused:
        candidate_containment_basis(test_db, run_id)
    assert "#10876" not in str(refused.value)
    close_attempt(test_db, 9877, "10877", "closed without merging")
    basis = candidate_containment_basis(test_db, run_id)
    assert basis["recorded_snapshot"]["items"] == items


def test_a_removed_member_open_correction_never_blocks_a_fresh_basis(
    test_db, monkeypatch
):
    from yoke_core.domain import deployment_run_containment_basis as basis_module
    from yoke_core.domain.deployment_run_member_removal import remove_member_on

    run_id = "removed-correction-fresh"
    _run_with_open_landings(test_db, run_id, (9876, 9877))
    monkeypatch.setattr(basis_module, "_delivery_item_ids", lambda *_args: (9876, 9877))
    remove_member_on(test_db, run_id, 9876, reason="rides a later release")
    with pytest.raises(ValueError, match="item_landing_open:.*#10877") as refused:
        basis_module.candidate_containment_basis(test_db, run_id)
    assert "#10876" not in str(refused.value)
    close_attempt(test_db, 9877, "10877", "closed without merging")
    assert basis_module.candidate_containment_basis(test_db, run_id)["projects"]


@pytest.mark.parametrize("outcome", ["closed", "merged"])
def test_release_guard_settles_stale_attempt_with_real_outcome(monkeypatch, outcome):
    from yoke_core.domain import deployment_landing_guard as guard
    from yoke_core.domain.merge_queue_landing_attempt import read_latest_attempt
    from runtime.api.domain.merge_queue_observer_test_helpers import MERGED
    from dataclasses import replace

    conn = observer_connection()
    record_attempt(conn, 101, "43", enqueued_at=None)
    state = MERGED if outcome == "merged" else replace(MERGED, merged=False)
    monkeypatch.setattr(guard, "read_pr_landing_state", lambda *_: (state, None))
    guard.require_closed_landing(conn, 101)
    attempt = read_latest_attempt(conn, 101)
    assert attempt["closed_at"] is not None
    assert ("promoted" in attempt["closed_reason"]) == (outcome == "merged")
    row = conn.execute(
        "SELECT merge_queue_pr_number,merged_at FROM items WHERE id=101"
    ).fetchone()
    assert row[0] == ("43" if outcome == "merged" else "42")
    assert bool(row[1]) == (outcome == "merged")
    conn.rollback()  # Reconciliation never commits its caller's transaction.
    assert read_latest_attempt(conn, 101) is None


def test_unreadable_correction_stays_open_and_names_recovery(monkeypatch):
    from yoke_core.domain import deployment_landing_guard as guard
    from yoke_core.domain.merge_queue_landing_attempt import read_open_attempt

    conn = observer_connection()
    record_attempt(conn, 101, "43", enqueued_at=None)
    monkeypatch.setattr(
        guard, "read_pr_landing_state", lambda *_: (None, "GitHub unavailable")
    )
    with pytest.raises(ValueError, match="repair GitHub read access and retry"):
        guard.require_closed_landing(conn, 101)
    assert read_open_attempt(conn, 101)["pr_number"] == "43"
