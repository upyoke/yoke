"""An open correction skips its carried item without holding the whole release."""

import pytest

from runtime.api.domain.deployment_run_create_stranded_dependents_test_support import (
    RELEASE_FLOW,
    _candidate,
)
from runtime.api.domain.merge_queue_observer_test_helpers import open_unarmed
from yoke_core.domain import deployment_landing_guard as guard
from yoke_core.domain.deployment_run_create_write import create_run
from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition
from yoke_core.domain.merge_queue_landing_attempt import record_attempt, close_attempt

CORRECTION, READY, OTHER_READY = 9801, 9802, 9803


def test_create_skips_open_correction_enrolls_ready_items_and_reports_reason(
    test_db, tmp_path, monkeypatch
):
    refs, tip = _candidate(
        test_db,
        tmp_path,
        monkeypatch,
        {item_id: "release" for item_id in (CORRECTION, READY, OTHER_READY)},
    )
    monkeypatch.setattr(guard, "read_pr_landing_state", open_unarmed)
    record_attempt(test_db, CORRECTION, "43", enqueued_at=None)
    test_db.commit()

    created = create_run("yoke", RELEASE_FLOW, release_lineage=tip)
    members = test_db.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
        (created.run_id,),
    ).fetchall()
    assert [row[0] for row in members] == [READY, OTHER_READY]
    ok, notice = cmd_validate_composition(created.run_id)
    assert ok, notice
    assert "Skipped 1 carried item(s)" in notice
    assert f"{refs[CORRECTION]} has open correction pull request #43" in notice
    assert "first release after their landing closes enrolls them" in notice
    with pytest.raises(ValueError, match="item_landing_open:.*#43"):
        cmd_add_item(created.run_id, CORRECTION)

    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded',completed_at='2026-11-01T00:00:00Z' WHERE id=%s",
        (created.run_id,),
    )
    close_attempt(test_db, CORRECTION, "43", "closed without merging")
    test_db.commit()
    successor = create_run("yoke", RELEASE_FLOW, release_lineage=tip)
    ok, notice = cmd_validate_composition(successor.run_id)
    assert ok, notice
    assert "open corrections" not in notice
    assert test_db.execute(
        "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (successor.run_id, CORRECTION),
    ).fetchone()
