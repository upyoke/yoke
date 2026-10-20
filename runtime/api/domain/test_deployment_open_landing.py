"""A delivered earlier landing cannot hide an open correction from a release."""

import pytest

from runtime.api.domain.merge_queue_observer_test_helpers import observer_connection
from yoke_core.domain.deployment_landing_guard import require_closed_landing
from yoke_core.domain.merge_queue_landing_attempt import record_attempt, close_attempt
from yoke_core.domain.deployment_run_member_admission import (
    MemberAdmission,
    admit_run_items,
)


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
