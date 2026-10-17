"""An item-bound create enrolls its item in the creation transaction.

The takeover, the enrollment and the composition check share one transaction:
an item the takeover already moved onto the new run is not enrolled twice,
and a failed enrollment leaves no run, membership or takeover behind.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.test_deployment_run_target_takeover import (
    NEW,
    NEW_LINEAGE,
    OLD,
    PASSED,
    WAITING,
    _close_passed,
    _contains,
    _members,
    _run,
    _seed_old,
)
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from yoke_core.domain import deployment_runs_validation
from yoke_core.domain.db_helpers import utc_now
from yoke_core.domain.deployment_run_create_composition import compose_run


def _compose(conn, item_id: int):
    old = conn.execute(
        "SELECT project_id,flow,target_tier,target_environment_id "
        "FROM deployment_runs WHERE id=%s",
        (OLD,),
    ).fetchone()
    return compose_run(
        conn,
        NEW,
        created_at=utc_now(),
        project_id=int(old["project_id"]),
        target=(old["target_tier"], old["target_environment_id"]),
        flow=old["flow"],
        release_lineage=NEW_LINEAGE,
        created_by="operator",
        artifact_identity=None,
        inherit_members_from=None,
        allow_pending_pair_merges=False,
        session_id=DRIVER_SESSION,
        enroll_item_id=item_id,
    )


@pytest.fixture
def composition_passes(monkeypatch):
    seen = {}

    def _validate(run_id, **kwargs):
        seen["require_item_qa_members"] = kwargs["require_item_qa_members"]
        return True, "ok"

    monkeypatch.setattr(
        deployment_runs_validation, "cmd_validate_composition", _validate
    )
    return seen


def test_an_item_the_takeover_moved_is_enrolled_once(
    test_db, monkeypatch, composition_passes
):
    _seed_old(test_db, run_qa=False)
    _close_passed(test_db)
    _contains(monkeypatch)

    assert _compose(test_db, WAITING) == (True, "ok")
    test_db.commit()

    assert _members(test_db, NEW) == {WAITING}
    assert _members(test_db, OLD) == {PASSED}
    assert _run(test_db, NEW)["supersedes_run_id"] == OLD
    assert composition_passes["require_item_qa_members"] is True
    creator = test_db.execute(
        "SELECT created_by_session_id FROM deployment_runs WHERE id=%s", (NEW,)
    ).fetchone()
    assert creator["created_by_session_id"] == DRIVER_SESSION


def test_a_failed_enrollment_leaves_no_run_and_no_takeover(
    test_db, monkeypatch, composition_passes
):
    from yoke_core.domain import deployment_run_item_qa_membership as membership

    _seed_old(test_db, run_qa=False)
    _close_passed(test_db)
    _contains(monkeypatch)

    def _refuse(*_a, **_k):
        raise ValueError("this run can never snapshot its item QA")

    monkeypatch.setattr(membership, "require_item_qa_membership_possible", _refuse)

    with pytest.raises(ValueError, match="never snapshot"):
        _compose(test_db, PASSED)
    test_db.rollback()

    assert _run(test_db, NEW) is None
    assert _members(test_db, OLD) == {PASSED, WAITING}
    assert _run(test_db, OLD)["superseded_by_run_id"] is None
