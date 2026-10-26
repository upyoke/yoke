"""A deliberate hold remains quiet until GitHub accepts a fresh arming."""

from dataclasses import replace

import pytest

from runtime.api.domain.merge_queue_observer_test_helpers import (
    ARMED_AWAITING_CHECKS,
    check_failed,
    in_queue,
    message_count,
    not_queued,
    observe,
    observer_connection,
)
from runtime.api.domain.test_session_message_support import NOW
from yoke_core.domain import merge_queue_landing_observer as observer
from yoke_core.domain.merge_queue_enqueue_verification import LandingReadback
from yoke_core.domain.merge_queue_landing_record import (
    from_readback,
    read_landing_record,
    write_landing_record,
)


@pytest.mark.parametrize("new_head", [False, True])
@pytest.mark.parametrize("queued", [False, True])
def test_hold_push_rearm_and_real_ejection(new_head, queued):
    conn = observer_connection()
    state = replace(ARMED_AWAITING_CHECKS, auto_merge_active=False)
    write_landing_record(conn, from_readback(
        item_id=101, project_id=1, pr_number="42", observed_at=NOW,
        readback=LandingReadback(
            state=state, membership=not_queued(None, None)[0],
            required_checks=(), queue_recovery={"action": "held"},
        ),
    ))
    conn.commit()

    def read_state(*_args):
        return state, None

    def read(*, membership=not_queued, failed=False):
        kwargs = {"read_checks": check_failed} if failed else {}
        return observe(conn, read_state=read_state,
                       read_membership=membership, **kwargs)

    assert read()["ejected"] == 0
    if new_head:
        state = replace(state, head_sha="ef" * 20)
    assert read(failed=True)["ejected"] == 0
    assert message_count(conn) == 0
    assert read_landing_record(conn, 101).recovery == {"action": "held"}

    state = replace(state, auto_merge_active=not queued)
    assert read(membership=in_queue if queued else not_queued)["ejected"] == 0
    assert read_landing_record(conn, 101).recovery.get("action") != "held"

    state = replace(state, auto_merge_active=False)
    assert read(failed=True)["ejected"] == 1
    assert message_count(conn) == 1


def test_hold_does_not_transfer_to_a_different_pull_request():
    conn = observer_connection()
    state = replace(ARMED_AWAITING_CHECKS, auto_merge_active=False)
    write_landing_record(conn, from_readback(
        item_id=101, project_id=1, pr_number="41", observed_at=NOW,
        readback=LandingReadback(
            state=state, membership=not_queued(None, None)[0],
            required_checks=(), queue_recovery={"action": "held"},
        ),
    ))
    conn.commit()
    assert observe(conn, read_state=lambda *_: (state, None),
                   read_membership=not_queued)["ejected"] == 1


def test_disarm_result_reaches_the_notice_and_durable_record(monkeypatch):
    conn = observer_connection()
    note = "disarm transport refused"
    passed_notes = []
    render = observer.ejection_message

    def capture(public_ref, pr_number, observation, route, disarm_note):
        passed_notes.append(disarm_note)
        return render(public_ref, pr_number, observation, route, disarm_note)

    monkeypatch.setattr(observer, "ejection_message", capture)
    result = observe(
        conn, read_state=lambda *_: (ARMED_AWAITING_CHECKS, None),
        read_membership=not_queued, read_checks=check_failed,
        disarm=lambda *_: note,
    )
    assert result["ejected"] == 1
    assert passed_notes == [note]
    assert read_landing_record(conn, 101).disarm_note == note
