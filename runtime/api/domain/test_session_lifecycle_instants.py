"""Native session/claim lifecycle writes and strict reclaim activity ordering."""

from datetime import timedelta
from uuid import uuid4

import pytest

from runtime.api.test_sessions import _insert_claimable_item, _register
from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import sessions_lifecycle_registry as registry
from yoke_core.domain import sessions_lifecycle_claim as claims
from yoke_core.domain import sessions_lifecycle_claim_release as release
from yoke_core.domain import sessions_lifecycle_release_bulk as bulk
from yoke_core.domain import sessions_render_end as ending
from yoke_core.domain.claim_chain_state import stamp_chain_checkpoint
from yoke_core.domain.idea_claim_events import compute_duration_ms
from yoke_core.domain.session_reclaim_activity import read_activity_signals
from yoke_core.domain.session_reclaim_activity_bulk import latest_activity_by_session
from yoke_core.domain.session_reclaim_progress import newest_activity_stamp


MOMENT = parse_instant("1969-12-31T23:59:59.123456Z")


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_session_claim_heartbeat_release_and_checkpoint_keep_native_precision(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    clock = [MOMENT]
    for owner in (registry, claims, release, bulk, ending):
        monkeypatch.setattr(owner, "utc_now", lambda: clock[0])
    session_id = str(uuid4())
    item_id = 91001
    _insert_claimable_item(test_db, item_id)
    _register(test_db, session_id=session_id)
    assert test_db.execute(
        "SELECT offered_at,last_heartbeat,episode_started_at FROM harness_sessions "
        "WHERE session_id=%s",
        (session_id,),
    ).fetchone() == (MOMENT, MOMENT, MOMENT)
    claim = claims.claim_work(test_db, session_id=session_id, item_id=item_id)
    assert claim["claimed_at"] == MOMENT
    clock[0] += timedelta(microseconds=1)
    registry.heartbeat(test_db, session_id)
    assert (
        test_db.execute(
            "SELECT last_heartbeat FROM work_claims WHERE id=%s", (claim["id"],)
        ).fetchone()[0]
        == clock[0]
    )
    evidence = read_activity_signals(test_db, session_id)
    assert evidence.activity_at == clock[0]
    assert evidence.as_payload()["activity_at"] == format_instant(clock[0])
    assert latest_activity_by_session(test_db, [session_id]) == {session_id: clock[0]}
    stamp_chain_checkpoint(test_db, session_id=session_id, step=1, at=clock[0])
    assert (
        test_db.execute(
            "SELECT last_checkpoint_at FROM harness_sessions WHERE session_id=%s",
            (session_id,),
        ).fetchone()[0]
        == clock[0]
    )
    released = release.release_claim_by_id(test_db, claim["id"])
    assert released["released_at"] == clock[0]
    claim = claims.claim_work(test_db, session_id=session_id, item_id=item_id)
    clock[0] += timedelta(microseconds=1)
    assert bulk.release_all_claims(test_db, session_id, reason="handed_off") == 1
    assert test_db.execute(
        "SELECT released_at,release_reason_intent FROM work_claims WHERE id=%s",
        (claim["id"],),
    ).fetchone() == (clock[0], "handed_off")
    ended = ending.end_session(test_db, session_id)
    assert ended["ended_at"] == clock[0]


def test_reclaim_order_is_native_and_duration_keeps_integer_milliseconds():
    before = "1970-01-01T05:29:59.999999+05:30"
    epoch = parse_instant("1970-01-01T00:00:00.000000Z")
    assert newest_activity_stamp(before, epoch, None) == epoch
    assert newest_activity_stamp(None, None) is None
    assert compute_duration_ms(MOMENT, MOMENT + timedelta(microseconds=1999)) == 1
    assert compute_duration_ms(MOMENT, MOMENT - timedelta(microseconds=1)) == 0
    assert compute_duration_ms(None, MOMENT) == 0
    with pytest.raises(InvalidInstant):
        newest_activity_stamp("1970-01-01T00:00:00", epoch)
    with pytest.raises(InvalidInstant):
        compute_duration_ms("1970-01-01T00:00:00", epoch)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_hook_claims_focus_and_pipe_output_keep_native_instants(
    test_db, monkeypatch, zone
):
    from yoke_core.hooks import sessions_claims_acquire as acquiring
    from yoke_core.hooks import sessions_claims as releasing
    from yoke_core.hooks import sessions_focus as focus
    from yoke_core.hooks import sessions_lifecycle as lifecycle

    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    clock = [MOMENT]
    for owner in (registry, acquiring, releasing, focus, lifecycle):
        monkeypatch.setattr(owner, "utc_now", lambda: clock[0])
    session_id = str(uuid4())
    item_id = 91002
    _insert_claimable_item(test_db, item_id)
    _register(test_db, session_id=session_id)
    assert "Claimed:" in acquiring.cmd_claim(
        test_db, session_id, "item", item_id=item_id
    )
    row = test_db.execute(
        "SELECT id,claimed_at,last_heartbeat FROM work_claims WHERE session_id=%s",
        (session_id,),
    ).fetchone()
    assert row["claimed_at"] == MOMENT
    assert format_instant(MOMENT) in releasing.cmd_list_claims(test_db, session_id)
    assert format_instant(MOMENT) in lifecycle.cmd_get(test_db, session_id)
    clock[0] += timedelta(microseconds=1)
    lifecycle.cmd_touch(test_db, session_id)
    focus._set_current_item(test_db, session_id, item_id)
    assert test_db.execute(
        "SELECT current_item_set_at,recent_item_recorded_at FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    ).fetchone() == (clock[0], MOMENT)
    assert (
        test_db.execute(
            "SELECT last_heartbeat FROM work_claims WHERE id=%s", (row["id"],)
        ).fetchone()[0]
        == clock[0]
    )
    assert "Released claim:" in releasing.cmd_release(test_db, row["id"])
    assert (
        test_db.execute(
            "SELECT released_at FROM work_claims WHERE id=%s", (row["id"],)
        ).fetchone()[0]
        == clock[0]
    )
