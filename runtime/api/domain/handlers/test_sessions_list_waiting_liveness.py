"""A parked session holding a work claim is waiting, never stale.

The roster's liveness is the one classification every display surface reads,
so a worker parked on purpose — at a deploy, a landing, a migration slot —
must not read as stale however long it has been quiet. ``reclaimable`` is the
separate per-row answer the Sessions page counts: whether the stale reclaim
sweep would act on the session, which an active work claim always prevents.
"""

from __future__ import annotations

from runtime.api.domain.handlers.test_sessions_list_handler import (
    _LONG_AGO_MINUTES,
    _insert_session,
)
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.session_holdings import insert_item_claim, iso
from yoke_core.domain.sessions_list_read import list_sessions
from yoke_core.domain.sessions_render_reclaim import find_stale_sessions


def _seed(test_db) -> None:
    quiet = iso(_LONG_AGO_MINUTES)
    _insert_session(test_db, "s-parked-holder", last_heartbeat=quiet, mode="parked")
    _insert_session(
        test_db, "s-fresh-parked-holder", last_heartbeat=iso(), mode="parked"
    )
    _insert_session(test_db, "s-quiet-holder", last_heartbeat=quiet)
    _insert_session(test_db, "s-parked-claimless", last_heartbeat=quiet, mode="parked")
    _insert_session(test_db, "s-quiet-claimless", last_heartbeat=quiet)
    _insert_session(test_db, "s-active", last_heartbeat=iso())
    for item_id in (81, 82, 83):
        insert_item(test_db, id=item_id, title=f"held item {item_id}")
    test_db.commit()
    insert_item_claim(test_db, "s-parked-holder", 81)
    insert_item_claim(test_db, "s-fresh-parked-holder", 82)
    insert_item_claim(test_db, "s-quiet-holder", 83)


def test_a_parked_claim_holder_is_waiting_whatever_its_age(test_db):
    _seed(test_db)

    by_id = {row["session_id"]: row for row in list_sessions()}

    assert by_id["s-parked-holder"]["liveness"] == "waiting"
    assert by_id["s-fresh-parked-holder"]["liveness"] == "waiting"
    # Neither half alone accounts for the quiet: an unparked holder and a
    # parked session holding nothing are still stale past their TTL.
    assert by_id["s-quiet-holder"]["liveness"] == "stale"
    assert by_id["s-parked-claimless"]["liveness"] == "stale"
    assert by_id["s-quiet-claimless"]["liveness"] == "stale"
    assert by_id["s-active"]["liveness"] == "active"


def test_the_liveness_filter_and_open_roster_carry_waiting_sessions(test_db):
    _seed(test_db)

    waiting = {row["session_id"] for row in list_sessions(liveness="waiting")}
    stale = {row["session_id"] for row in list_sessions(liveness="stale")}
    opened = {row["session_id"] for row in list_sessions(open=True)}

    assert waiting == {"s-parked-holder", "s-fresh-parked-holder"}
    assert waiting.isdisjoint(stale)
    assert waiting <= opened


def test_reclaimable_matches_what_the_reclaim_sweep_would_act_on(test_db):
    _seed(test_db)

    reclaimable = {row["session_id"] for row in list_sessions() if row["reclaimable"]}
    swept = {row["session_id"] for row in find_stale_sessions(test_db)}

    # Every claim holder is protected from the sweep, parked or not.
    assert reclaimable == {"s-parked-claimless", "s-quiet-claimless"}
    assert reclaimable == swept
