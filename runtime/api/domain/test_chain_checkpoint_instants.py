"""Chain documents format their one clock while session SQL facts remain native."""

import json
from uuid import uuid4

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.timestamps import (
    InvalidInstant,
    format_instant,
    parse_instant,
    temporal_wire,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain import sessions_queries_chain as chain
from yoke_core.domain import sessions_render_reclaim as reclaim
from yoke_core.domain.sessions import claim_work


MOMENT = parse_instant("2026-11-01T05:29:59.123456+05:45")
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]


def _session(conn, *, envelope=None):
    session = str(uuid4())
    actor = seed_human_actor(conn)
    conn.execute(
        "INSERT INTO harness_sessions (session_id,executor,provider,model,workspace,"
        "actor_id,project_id,offered_at,last_heartbeat,offer_envelope) "
        "VALUES (%s,'codex','openai','clock-test','/tmp',%s,1,%s,%s,%s)",
        (
            session,
            actor,
            MOMENT,
            MOMENT,
            json.dumps(envelope) if envelope is not None else None,
        ),
    )
    return session


@pytest.mark.parametrize("zone", ZONES)
def test_chain_checkpoint_native_read_matches_scalar_and_finite_wire_clock(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(chain, "utc_now", lambda: MOMENT)
    opaque = {
        "capture": {"completed_at": "unparsed-capture-clock"},
        "offer_id": "opaque",
    }
    session = _session(test_db, envelope=opaque)
    checkpoint = chain.update_chain_checkpoint(
        test_db, session, step=2, action="continue", chainable=True
    )
    assert checkpoint["completed_at"] == MOMENT
    assert chain.read_chain_checkpoint(test_db, session) == checkpoint
    row = test_db.execute(
        "SELECT offer_envelope,last_checkpoint_at,last_chain_step FROM harness_sessions WHERE session_id=%s",
        (session,),
    ).fetchone()
    envelope = json.loads(row["offer_envelope"])
    assert envelope["chain_checkpoint"] == temporal_wire(checkpoint)
    assert envelope["chain_checkpoint"]["completed_at"] == format_instant(MOMENT)
    assert envelope["capture"] == opaque["capture"]
    assert (row["last_checkpoint_at"], row["last_chain_step"]) == (MOMENT, 2)
    assert chain.clear_chain_checkpoint(test_db, session) == checkpoint
    assert chain.read_chain_checkpoint(test_db, session) is None
    stored = test_db.execute(
        "SELECT offer_envelope FROM harness_sessions WHERE session_id=%s", (session,)
    ).fetchone()[0]
    assert json.loads(stored) == opaque


@pytest.mark.parametrize("clock", ["", "2026-11-01T00:00:00", 0])
def test_invalid_chain_clock_refuses_without_rewriting_envelope(test_db, clock):
    raw = {"chain_checkpoint": {"step": 2, "completed_at": clock}, "capture": "opaque"}
    session = _session(test_db, envelope=raw)
    for operation in (chain.read_chain_checkpoint, chain.clear_chain_checkpoint):
        with pytest.raises(InvalidInstant):
            operation(test_db, session)
        stored = test_db.execute(
            "SELECT offer_envelope FROM harness_sessions WHERE session_id=%s",
            (session,),
        ).fetchone()[0]
        assert json.loads(stored) == raw


@pytest.mark.parametrize("zone", ZONES)
def test_reclaim_and_handoff_keep_native_clock_facts(test_db, monkeypatch, zone):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(reclaim, "utc_now", lambda: MOMENT)
    monkeypatch.setattr(reclaim, "settle_and_notify", lambda *_args, **_kwargs: None)
    source = _session(test_db)
    target = _session(test_db)
    item = 42
    insert_item(test_db, id=item)
    old = claim_work(test_db, session_id=source, item_id=item)
    new = reclaim.handoff_claim(test_db, old["id"], target)
    assert (new["claimed_at"], new["last_heartbeat"]) == (MOMENT, MOMENT)
    released = test_db.execute(
        "SELECT released_at FROM work_claims WHERE id=%s", (old["id"],)
    ).fetchone()[0]
    assert released == MOMENT
    session = _session(test_db, envelope={"capture": "opaque"})
    ended = reclaim.reclaim_stale_session(test_db, session)
    assert ended["ended_at"] == MOMENT
    stored = test_db.execute(
        "SELECT ended_at,pg_typeof(ended_at)::text FROM harness_sessions WHERE session_id=%s",
        (session,),
    ).fetchone()
    assert stored == (MOMENT, "timestamp with time zone")
