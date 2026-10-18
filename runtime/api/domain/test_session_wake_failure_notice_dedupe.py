"""An existing derived failure notice avoids rebuilding its recipients."""

from datetime import timedelta

from runtime.api.domain.test_session_message_support import (
    NOW_TEXT,
    message_connection,
)
from runtime.api.domain.test_session_wake_failure_notice import (
    SWEEP,
    _fail,
    _parked_recipient,
)
from yoke_core.domain import session_wake_failure_notice as notices
from yoke_core.domain.session_message_wake import wake_eligible_recipients


def test_duplicate_skips_recipient_resolution_but_cancelled_notice_does_not(
    monkeypatch,
):
    conn = message_connection()
    _parked_recipient(conn)
    conn.execute(
        "INSERT INTO item_strategy_docs VALUES (101,1,'AREA-PLAN',?)",
        (NOW_TEXT,),
    )
    conn.execute(
        "INSERT INTO work_claims (id,session_id,target_kind,scope,claimed_at) "
        "VALUES (5,'s1','steering','{\"project_id\":1,\"document\":\"AREA-PLAN\"}',?)",
        (NOW_TEXT,),
    )
    conn.commit()
    candidate = wake_eligible_recipients(conn, now=SWEEP)[0]
    _fail(conn, candidate)
    notice = notices.notify_failed_wake(conn, candidate, now=SWEEP, max_attempts=3)
    assert notice
    original = notices.resolve_recipients
    resolutions = []

    def observe(*args, **kwargs):
        resolutions.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(notices, "resolve_recipients", observe)
    for offset in range(1, 4):
        assert (
            notices.notify_failed_wake(
                conn, candidate, now=SWEEP + timedelta(seconds=offset), max_attempts=3
            )
            is None
        )
    assert resolutions == []
    conn.execute(
        "UPDATE session_messages SET cancelled_at=? WHERE message_id=?",
        (SWEEP.isoformat(), notice),
    )
    replacement = notices.notify_failed_wake(conn, candidate, now=SWEEP, max_attempts=3)
    assert replacement and replacement != notice
    assert resolutions


def test_new_failure_identity_still_routes_a_notice():
    conn = message_connection()
    _parked_recipient(conn)
    candidate = wake_eligible_recipients(conn, now=SWEEP)[0]
    _fail(conn, candidate)
    first = notices.notify_failed_wake(conn, candidate, now=SWEEP, max_attempts=3)
    candidate["wake_attempt_count"] = 3
    exhausted = notices.notify_failed_wake(conn, candidate, now=SWEEP, max_attempts=3)
    assert first and exhausted and first != exhausted
