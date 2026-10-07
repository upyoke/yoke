"""A waiting item-QA member's wake state is read from its stored notice.

A pending wake and a missing one used to look identical on the fleet
report, so steering messaged owners by hand. Each member now reads as
pending, woken, or not woken with the reason — from the existing
``deployment-qa-stage-wait`` notices and ``deployment-qa-member-failure``
handoffs, not a parallel record.
"""

from __future__ import annotations

import pytest

from runtime.api.steering_fleet_test_helpers import (
    JUST_NOW,
    PROJECT_ID,
    WORKER_SESSION,
    seed_message,
    seed_session,
    seed_steering_scope,
)
from yoke_core.domain.deployment_qa_failure_handoff import failure_handoff_key
from yoke_core.domain.deployment_qa_stage_wake import stage_wait_idempotency_key
from yoke_core.domain.deployment_qa_stage_wake_state import member_wake_states


RUN_ID = "run-20261007-024"
STAGE = "item-qa"
MEMBER = 3769
OTHER_MEMBER = 3770


def _state(conn, *, driver_live: bool = False, member: int = MEMBER) -> str:
    return member_wake_states(
        conn,
        run_id=RUN_ID,
        stage_name=STAGE,
        item_ids=[member],
        project_id=PROJECT_ID,
        driver_live=driver_live,
    )[member]


def _notice(
    conn, message_id: str, *, state: str, member: int = MEMBER, key=None, **kw
) -> None:
    seed_message(
        conn,
        message_id,
        sender=None,
        to=WORKER_SESSION,
        at=JUST_NOW,
        state=state,
        idempotency_key=key
        or stage_wait_idempotency_key(RUN_ID, STAGE, member, "digest"),
        **kw,
    )
    conn.commit()


@pytest.fixture
def scoped(test_db):
    return seed_steering_scope(test_db)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("acknowledged", "woken 11:58Z, acknowledged"),
        ("injected", "woken 11:58Z, not acknowledged"),
        ("pending", "woken 11:58Z, not yet delivered"),
        ("expired", "not woken: the wake sent 11:58Z expired undelivered"),
        ("cancelled", "not woken: the wake sent 11:58Z was cancelled"),
    ],
)
def test_a_stored_notice_reads_as_woken_or_failed(scoped, state, expected) -> None:
    _notice(scoped, "wake-1", state=state)

    assert _state(scoped) == expected
    # Driver liveness never hides a notice that already went out.
    assert _state(scoped, driver_live=True) == expected


def test_an_escalated_undelivered_wake_reads_as_failed(scoped) -> None:
    _notice(scoped, "wake-1", state="pending")
    scoped.execute(
        "UPDATE session_message_recipients SET wake_escalation='relay_unreachable'"
    )
    scoped.commit()

    assert _state(scoped) == (
        "not woken: the wake sent 11:58Z failed (relay_unreachable)"
    )


def test_no_notice_under_a_live_driver_is_pending(scoped) -> None:
    assert _state(scoped, driver_live=True) == (
        "wake pending (driver live, not yet sent)"
    )


def test_no_notice_without_a_driver_names_the_redrive(scoped) -> None:
    assert _state(scoped) == (
        f"not woken: driver gone or stale; re-drive {RUN_ID} to send it"
    )


def test_cancelled_and_other_member_notices_do_not_count(scoped) -> None:
    _notice(scoped, "wake-cancelled", state="pending", cancelled_at=JUST_NOW)
    _notice(scoped, "wake-other", state="acknowledged", member=OTHER_MEMBER)

    assert _state(scoped).startswith("not woken: driver gone or stale")
    assert _state(scoped, member=OTHER_MEMBER) == "woken 11:58Z, acknowledged"


def test_nobody_addressable_is_named(test_db) -> None:
    seed_session(test_db, WORKER_SESSION)
    test_db.commit()

    assert _state(test_db) == (
        "not woken: no addressable holder (no live claim holder and no "
        "covering steering seat); staff the item"
    )


def test_a_failed_members_qa_failure_handoff_reads_as_its_wake(scoped) -> None:
    _notice(
        scoped,
        "handoff-1",
        state="injected",
        key=failure_handoff_key(RUN_ID, STAGE, MEMBER, "digest", 77),
    )

    assert _state(scoped) == "woken 11:58Z by QA failure handoff, not acknowledged"


def test_several_recipients_read_as_the_furthest_any_got(scoped) -> None:
    seed_session(scoped, "second-recipient")
    _notice(scoped, "wake-1", state="pending")
    scoped.execute(
        "INSERT INTO session_message_recipients "
        "(message_id, session_id, project_id, resolution_evidence, "
        "routing_snapshot, state, created_at, wake_after, injection_count) "
        "VALUES ('wake-1', 'second-recipient', %s, '{}', '{}', 'acknowledged', "
        "%s, %s, 1)",
        (PROJECT_ID, JUST_NOW, JUST_NOW),
    )
    scoped.commit()

    assert _state(scoped) == "woken 11:58Z, acknowledged"


def test_one_batched_read_answers_every_member(scoped) -> None:
    _notice(scoped, "wake-1", state="acknowledged")

    states = member_wake_states(
        scoped,
        run_id=RUN_ID,
        stage_name=STAGE,
        item_ids=[MEMBER, OTHER_MEMBER],
        project_id=PROJECT_ID,
        driver_live=False,
    )

    assert states == {
        MEMBER: "woken 11:58Z, acknowledged",
        OTHER_MEMBER: f"not woken: driver gone or stale; re-drive {RUN_ID} to send it",
    }
