"""A takeover leaves out a moved member whose hard-block blocker does not ship.

The older run waits on item QA with WAITING still open. When WAITING depends
on an item that neither moves with it nor has shipped, creation does not
refuse the whole run: WAITING is set aside on the older run with its QA, the
new run reports it as skipped, and the first release after its blocker
ships enrolls it. A blocker that ships in the same run still releases it.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.domain import test_deployment_run_create_takeover_enrollment as seeded
from runtime.api.domain.structural_status_gate_test_helpers import insert_dependency
from yoke_core.domain.deployment_run_blocked_dependents import (
    BLOCKED_SET_ASIDE_REASON,
)
from yoke_core.domain.deployment_run_membership_removals import membership_removals
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition

BLOCKER = seeded.BLOCKER


def _removal_reasons(conn: Any, run_id: str) -> dict[int, str]:
    return {
        int(entry["item_id"]): str(entry["reason"])
        for entry in membership_removals(conn, run_id)
    }


def test_takeover_leaves_out_a_dependent_whose_blocker_was_removed(
    test_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded._seed(test_db, monkeypatch, flow=None, depend_on_blocker=False)
    # The blocker went back for rework after its landing, so nothing ships it.
    test_db.execute("UPDATE items SET status='implementing' WHERE id=%s", (BLOCKER,))
    insert_dependency(test_db, takeover.WAITING, BLOCKER, "activation", "status:done")

    created = seeded._create()

    assert takeover._run(test_db, takeover.OLD)["superseded_by_run_id"] == created
    assert takeover.WAITING not in takeover._members(test_db, created)
    assert takeover.WAITING not in takeover._members(test_db, takeover.OLD)
    assert (
        _removal_reasons(test_db, takeover.OLD)[takeover.WAITING]
        == BLOCKED_SET_ASIDE_REASON
    )
    ok, notice = cmd_validate_composition(created)
    assert ok, notice
    assert "blocked by" in notice and "first release after the blocker ships" in notice
    # Its QA waits for the release that enrolls it, not cancelled.
    open_rows = test_db.execute(
        "SELECT count(*) AS n FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id=%s AND retracted_at IS NULL",
        (takeover.OLD, takeover.WAITING),
    ).fetchone()
    assert open_rows["n"] > 0


def test_a_dependent_whose_blocker_moves_with_it_still_moves(
    test_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded._seed(test_db, monkeypatch, flow=None, depend_on_blocker=False)
    insert_dependency(
        test_db, takeover.WAITING, takeover.PASSED, "activation", "status:done"
    )

    created = seeded._create()

    assert {takeover.PASSED, takeover.WAITING} <= takeover._members(test_db, created)
    assert takeover.WAITING not in _removal_reasons(test_db, takeover.OLD) or (
        _removal_reasons(test_db, takeover.OLD)[takeover.WAITING]
        != BLOCKED_SET_ASIDE_REASON
    )


def test_a_dependent_whose_blocker_enrolls_as_carried_work_still_ships(
    test_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded._seed(test_db, monkeypatch, flow=None, depend_on_blocker=False)
    insert_dependency(test_db, takeover.WAITING, BLOCKER, "activation", "status:done")
    before = seeded._qa_rows(test_db)

    created = seeded._create()

    assert {takeover.WAITING, BLOCKER} <= takeover._members(test_db, created)
    # Its QA is the same rows, now owned by the run that enrolled it.
    assert seeded._qa_rows(test_db, created) == before
    owners = test_db.execute(
        "SELECT DISTINCT deployment_run_id FROM qa_requirements "
        "WHERE deployment_member_item_id=%s AND retracted_at IS NULL",
        (takeover.WAITING,),
    ).fetchall()
    assert {row["deployment_run_id"] for row in owners} == {created}
