"""Landed-but-open rows: who owes the close-out, and what runs for them.

A landing needs a seat only when no live session holds it, and the command
that seat should run depends on the item's own workflow. Both answers used to
be missing from the row, so every landing printed the same un-gated command
whether or not anybody needed one.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.steering_fleet_test_helpers import (
    ASKER,
    BEFORE_THAT,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    seed_session,
)
from yoke_core.domain.delivery_landing_custody import UNHELD
from yoke_core.domain.steering_fleet_report_holders import claim_holders
from yoke_core.domain.steering_fleet_report_landed_open import (
    custody_phrase,
    holder_phrase,
    landed_recovery,
    landed_without_closeout,
)


def _landed(conn):
    """The landed rows, built from the same holder facts the report shares."""
    return landed_without_closeout(
        conn,
        project_id=PROJECT_ID,
        now=NOW,
        holders=claim_holders(conn, project_id=PROJECT_ID, now=NOW),
    )


@pytest.fixture
def fleet(test_db):
    """One live worker and one dash item, before any landing is introduced."""
    seed_session(test_db, ASKER, last_tool_call_at=BEFORE_THAT)
    insert_item(
        test_db,
        id=1,
        title="Some work",
        workflow_id="dash",
        status="implementing",
        created_at=LONG_AGO,
        updated_at=LONG_AGO,
    )
    test_db.commit()
    return test_db


def _park(conn, session_id: str, reason: str) -> None:
    """Park a holder the way a worker waiting on its delivery parks itself."""
    conn.execute(
        "UPDATE harness_sessions SET mode = 'parked', quiet_reason = %s "
        "WHERE session_id = %s",
        (reason, session_id),
    )


def test_a_merged_branch_on_an_open_item_is_reported(fleet):
    fleet.execute("UPDATE items SET merged_at = %s WHERE id = 1", (LONG_AGO,))
    fleet.commit()

    landed = _landed(fleet)

    assert [entry.item_id for entry in landed] == [1]
    assert landed[0].status == "implementing"
    assert landed[0].landed_seconds == 3 * 3600


def test_a_landing_no_release_names_is_reported_as_stranded(fleet):
    """The row that used to read like any other item waiting on a delivery.

    No release names this item, so nothing is bringing its code to an
    environment and the row has to say so rather than look like a wait.
    """
    fleet.execute("UPDATE items SET merged_at = %s WHERE id = 1", (LONG_AGO,))
    fleet.commit()

    landed = _landed(fleet)

    assert landed[0].custody_state == UNHELD
    assert landed[0].custody_run_id == ""
    assert landed[0].stranded is True
    assert "no release holds it" in custody_phrase(landed[0])


def test_a_merged_branch_on_a_closed_item_is_not_reported(fleet):
    fleet.execute(
        "UPDATE items SET merged_at = %s, status = 'done' WHERE id = 1",
        (LONG_AGO,),
    )
    fleet.commit()

    assert _landed(fleet) == ()


def test_a_queue_landing_counts_as_the_branch_landing(fleet):
    fleet.execute(
        "UPDATE items SET merge_queue_landed_at = %s WHERE id = 1",
        (LONG_AGO,),
    )
    fleet.commit()

    landed = _landed(fleet)

    assert [entry.item_id for entry in landed] == [1]
    # Nothing holds the item, and that is the answer the report needs: this
    # landing needs a seat rather than a message.
    assert landed[0].holder_session_id == ""


def _claim_item(conn, session_id: str, *, item_id: int = 1, **columns) -> None:
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claimed_at, last_heartbeat, released_at) "
        "VALUES (%s, 'item', %s, %s, %s, %s)",
        (
            session_id,
            json.dumps({"item_id": item_id}),
            LONG_AGO,
            LONG_AGO,
            columns.get("released_at"),
        ),
    )


def test_a_landing_its_claim_holder_still_holds_names_that_session(fleet):
    """Close-out holds the claim, so the holder IS the recovery path."""
    fleet.execute("UPDATE items SET merged_at = %s WHERE id = 1", (LONG_AGO,))
    _claim_item(fleet, ASKER)
    fleet.commit()

    landed = _landed(fleet)

    assert landed[0].holder_session_id == ASKER


def test_a_landing_whose_holder_ended_reports_no_live_holder(fleet):
    """An ended session cannot be asked to close out.

    Naming it would point the seat at a recovery that cannot happen, which
    is the state this row exists to make actionable.
    """
    fleet.execute("UPDATE items SET merged_at = %s WHERE id = 1", (LONG_AGO,))
    fleet.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (LONG_AGO, ASKER),
    )
    _claim_item(fleet, ASKER)
    fleet.commit()

    landed = _landed(fleet)

    assert landed[0].holder_session_id == ""


def test_a_released_claim_is_not_a_live_holder(fleet):
    fleet.execute("UPDATE items SET merged_at = %s WHERE id = 1", (LONG_AGO,))
    _claim_item(fleet, ASKER, released_at=NOW)
    fleet.commit()

    landed = _landed(fleet)

    assert landed[0].holder_session_id == ""


def test_a_landing_its_parked_holder_waits_on_offers_no_command(fleet):
    """The healthy row. A parked holder is waiting on its own delivery.

    Nine of these carried a close-out recipe at once, and every seat that
    followed one spent the attempt to find out nothing was wrong. State is
    what this row owes a reader; a command is not.
    """
    fleet.execute("UPDATE items SET merged_at = %s WHERE id = 1", (LONG_AGO,))
    _claim_item(fleet, ASKER)
    _park(fleet, ASKER, "awaiting YOK-1 delivery: deployment run, then close-out")
    fleet.commit()

    entry = _landed(fleet)[0]

    assert entry.holder_parked is True
    assert landed_recovery(entry) == ""
    assert "parked" in holder_phrase(entry)
    assert "awaiting YOK-1 delivery" in holder_phrase(entry)


def test_a_parked_holder_that_left_no_reason_still_reads_as_waiting(fleet):
    """A park without words is still a wait, and must not read as silence."""
    fleet.execute("UPDATE items SET merged_at = %s WHERE id = 1", (LONG_AGO,))
    _claim_item(fleet, ASKER)
    fleet.execute(
        "UPDATE harness_sessions SET mode = 'parked' WHERE session_id = %s",
        (ASKER,),
    )
    fleet.commit()

    assert "waiting on delivery" in holder_phrase(_landed(fleet)[0])


def test_a_landing_a_working_holder_owns_offers_no_command_either(fleet):
    """Close-out is claim-holding, so the seat is refused by name here too."""
    fleet.execute("UPDATE items SET merged_at = %s WHERE id = 1", (LONG_AGO,))
    _claim_item(fleet, ASKER)
    fleet.commit()

    entry = _landed(fleet)[0]

    assert entry.holder_parked is False
    assert landed_recovery(entry) == ""
    assert holder_phrase(entry) == f"held by {ASKER}, working"


def test_an_unheld_landing_on_a_gated_workflow_names_the_flags_it_needs(fleet):
    """The command the row prints has to be the command that runs.

    A dash terminal transition is evidence-gated, so the bare form is refused
    and the reader composes the real one from a denial instead of from the
    row. Naming the flags is what moves that discovery back to the report.
    """
    fleet.execute("UPDATE items SET merged_at = %s WHERE id = 1", (LONG_AGO,))
    fleet.commit()

    recovery = landed_recovery(_landed(fleet)[0])

    assert "yoke merge item YOK-1" in recovery
    assert "--result" in recovery
    assert "--verification" in recovery


def test_an_unheld_landing_on_an_ungated_workflow_gets_the_bare_command(fleet):
    """Flags a workflow does not gate on would send a reader composing air."""
    fleet.execute(
        "UPDATE items SET merged_at = %s, workflow_id = 'issue' WHERE id = 1",
        (LONG_AGO,),
    )
    fleet.commit()

    recovery = landed_recovery(_landed(fleet)[0])

    assert "yoke merge item YOK-1" in recovery
    assert "--result" not in recovery
