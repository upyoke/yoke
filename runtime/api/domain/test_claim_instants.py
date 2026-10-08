"""Claims and posture keep native instants while their public projections are canonical."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant
from yoke_contracts.session_control.private_route_qualification import (
    qualification_expires_at,
)
from yoke_core.domain import coordination_claims
from yoke_core.domain.coordination_claim_record import claim_as_dict
from yoke_core.domain.coordination_claims_listing import stale_claim_candidates
from yoke_core.domain.session_turn_posture import stamp_turn_posture
from yoke_core.domain.work_claim_targets import make_deploy_serialization_target


INSTANT = datetime(
    1969, 12, 31, 18, 29, 59, 123456, timezone(timedelta(hours=-5, minutes=-30))
)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_claim_and_posture_preserve_microseconds_and_nulls(test_db, zone):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    project_id = test_db.execute(
        "SELECT id FROM projects ORDER BY id LIMIT 1"
    ).fetchone()[0]
    session_id = str(uuid4())
    test_db.execute(
        "INSERT INTO harness_sessions "
        "(session_id,executor,provider,model,workspace,project_id,offered_at,last_heartbeat) "
        "VALUES (%s,'codex','openai','gpt','/tmp',%s,%s,%s)",
        (session_id, project_id, INSTANT, INSTANT),
    )
    target = make_deploy_serialization_target(project_id, "native-clock")
    claim = coordination_claims.acquire(test_db, target, session_id, now=INSTANT)
    assert claim.claimed_at == INSTANT
    assert claim.released_at is None
    wire = claim_as_dict(claim)
    assert wire["claimed_at"] == "1969-12-31T23:59:59.123456Z"
    assert wire["released_at"] is None
    assert claim in stale_claim_candidates(
        test_db, threshold_iso=INSTANT + timedelta(microseconds=1)
    )
    assert claim not in stale_claim_candidates(test_db, threshold_iso=INSTANT)
    edge = INSTANT + timedelta(microseconds=1)
    refreshed = coordination_claims.heartbeat(test_db, claim.id, now=edge)
    assert refreshed.last_heartbeat == edge
    assert stamp_turn_posture(
        test_db, session_id=session_id, posture="running", observed_at=edge
    )
    assert not stamp_turn_posture(
        test_db, session_id=session_id, posture="waiting", observed_at=INSTANT
    )
    stored, kind = test_db.execute(
        "SELECT turn_posture_at,pg_typeof(turn_posture_at)::text FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    ).fetchone()
    assert stored == edge
    assert kind == "timestamp with time zone"
    released = coordination_claims.release(test_db, claim.id, "complete", now=edge)
    assert released.released_at == edge
    assert claim_as_dict(released)["released_at"] == format_instant(edge)


def test_private_qualification_expiry_keeps_microseconds_and_refuses_naive():
    assert qualification_expires_at(INSTANT) == "1970-01-01T00:29:59.123456Z"
    with pytest.raises(InvalidInstant):
        qualification_expires_at(INSTANT.replace(tzinfo=None))
