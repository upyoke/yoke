"""Supplemental proof follows the landing's ancestry, for own and bound projects."""

import pytest

from runtime.api.domain.test_release_member_target_enrollment import _pair
from runtime.api.fixtures.supplemental_credit import topology, pin, clone_run
from yoke_core.domain.deployment_item_completion_runs import (
    latest_qa_member_run,
    uncredited_supplemental_notice,
)
from yoke_core.domain.deployment_run_member_targeting import holder_covers_run
from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item


@pytest.mark.parametrize("carrier", [False, True])
@pytest.mark.parametrize("candidate", ["stage", "unrelated"])
def test_credit_and_add_item_use_current_landing(
    test_db, tmp_path, monkeypatch, carrier, candidate
):
    item = 9790
    _pair(test_db, item_id=item)
    commits = topology(test_db, tmp_path, monkeypatch, item)
    pin(
        test_db,
        "run-prod",
        commits["landing"],
        carrier=carrier,
        delivered=commits["prod"],
    )
    pin(test_db, "run-stage", commits[candidate], carrier=carrier)
    test_db.execute("UPDATE deployment_runs SET status='succeeded'")
    test_db.commit()
    credited = candidate == "stage"
    run = latest_qa_member_run(test_db, item_id=item, target_env="stage")
    assert (run is not None and run["id"] == "run-stage") is credited
    assert (
        holder_covers_run(
            test_db, holder_id="run-prod", run_id="run-stage", item_id=item
        )
        is False
    )
    notice = uncredited_supplemental_notice(test_db, run_id="run-stage", item_id=item)
    assert (notice == "") is credited
    if not credited:
        assert "supplemental_proof_not_credited" in notice
        assert commits[candidate] in notice and commits["landing"] in notice

    clone_run(test_db, "run-stage-new", "run-stage", commits[candidate])
    pin(test_db, "run-stage-new", commits[candidate], carrier=carrier)
    test_db.execute(
        "UPDATE deployment_runs SET status='created' WHERE id='run-stage-new'"
    )
    test_db.commit()
    result = cmd_add_item("run-stage-new", item)
    assert ("supplemental_proof_not_credited" not in result) is credited
    assert (
        test_db.execute(
            "SELECT item_id FROM deployment_run_items WHERE run_id='run-stage-new'"
        ).fetchone()[0]
        == item
    )
