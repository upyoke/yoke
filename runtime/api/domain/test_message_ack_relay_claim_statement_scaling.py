"""Acknowledge and relay claim cost does not grow with open QA wait wakes.

Both paths expire due receipts inside their own request. That expiry
used to re-read every open deployment QA wait's run, member and stage
acceptance in the same transaction, so a 54-member item-qa stage pushed
acknowledge from milliseconds to minutes and starved the relay poll.
These count statements across a small and a large pile of open waits;
the counts must match.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.session_launch_test_support import (
    NOW as RELAY_NOW,
    add_relay,
    relay_connection,
)
from runtime.api.domain.test_deployment_qa_stage_wake_withdraw import (
    NOW,
    RUN_ID,
    STAGE,
    _executing_run,
    _message,
    _seed_member,
    _wait,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import _project
from runtime.api.fixtures.statement_counter import CountingConnection
from yoke_core.domain.deployment_qa_stage_wake import (
    DEPLOYMENT_QA_STAGE_WAIT_PREFIX,
    stage_wait_idempotency_key,
)
from yoke_core.domain.session_message_delivery import expire_due_recipients
from yoke_core.domain.session_message_receipts import acknowledge_message
from yoke_core.domain.session_relay import claim_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat


FIRST_MEMBER = 9800
SMALL_PILE = 2
LARGE_PILE = 12
MACHINE_ID = "22222222-2222-4222-8222-222222222222"
RELAY_ID = f"machine:{MACHINE_ID}"
LATER = "2026-12-31T00:00:00.000000Z"


def _holder(item_id: int) -> str:
    return f"sess-holder-{item_id}"


def _open_waits(conn: Any, item_ids: range) -> None:
    for item_id in item_ids:
        _seed_member(conn, item_id, _holder(item_id))
        conn.commit()
        _wait(conn, item_id)


def _acknowledge_statements(conn: Any, item_id: int) -> int:
    message_id, _cancelled, _reason = _message(
        conn, stage_wait_idempotency_key(RUN_ID, STAGE, item_id)
    )
    counted = CountingConnection(conn)
    acknowledge_message(
        counted, message_id=message_id, session_id=_holder(item_id), now=NOW
    )
    return counted.count


def test_acknowledge_cost_is_flat_in_open_wait_wakes(test_db: Any) -> None:
    _project(test_db)
    _executing_run(test_db)
    test_db.commit()
    _open_waits(test_db, range(FIRST_MEMBER, FIRST_MEMBER + SMALL_PILE))
    small = _acknowledge_statements(test_db, FIRST_MEMBER)

    _open_waits(
        test_db, range(FIRST_MEMBER + SMALL_PILE, FIRST_MEMBER + LARGE_PILE)
    )
    large = _acknowledge_statements(test_db, FIRST_MEMBER + 1)

    assert large == small


def test_receipt_expiry_cost_is_flat_in_open_wait_wakes(test_db: Any) -> None:
    _project(test_db)
    _executing_run(test_db)
    test_db.commit()
    counts = []
    for start, stop in ((0, SMALL_PILE), (SMALL_PILE, LARGE_PILE)):
        _open_waits(test_db, range(FIRST_MEMBER + start, FIRST_MEMBER + stop))
        counted = CountingConnection(test_db)
        expire_due_recipients(counted, now=NOW)
        counts.append(counted.count)
    assert counts[0] == counts[1]


def _plant_relay_waits(conn: Any, count: int, offset: int) -> None:
    """Open waits not yet due to wake, so only a sweep would read them.

    The relay fixture has no run or QA tables: a sweep that re-read a
    wait's subject would fail here, not just cost more.
    """
    for index in range(offset, offset + count):
        message_id = f"wait-{index}"
        conn.execute(
            "INSERT INTO harness_sessions (session_id,project_id,workspace) "
            "VALUES (?,?,?)",
            (f"held-{index}", 10, "/held"),
        )
        conn.execute(
            "INSERT INTO session_messages (message_id,body,body_sha256,"
            "selector_snapshot,idempotency_key,created_at,expires_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                message_id,
                "wait",
                "sha",
                "{}",
                f"{DEPLOYMENT_QA_STAGE_WAIT_PREFIX}run-1:item-qa:{index}:",
                RELAY_NOW,
                LATER,
            ),
        )
        conn.execute(
            "INSERT INTO session_message_recipients (message_id,session_id,"
            "project_id,resolution_evidence,routing_snapshot,created_at,"
            "wake_after) VALUES (?,?,?,?,?,?,?)",
            (message_id, f"held-{index}", 10, "{}", "{}", RELAY_NOW, LATER),
        )
    conn.commit()


def _relay_claim_statements(conn: Any) -> int:
    counted = CountingConnection(conn)
    claim_relay_job(
        counted,
        RelayHeartbeat(
            relay_id=RELAY_ID,
            actor_id=1,
            machine_id=MACHINE_ID,
            hostname="relay-host",
            relay_version="0.1.1",
            surface_versions={"codex-cli": "0.148.0a15"},
            project_ids=(10,),
        ),
        wait_seconds=0,
        now_provider=lambda: RELAY_NOW,
    )
    return counted.count


def test_relay_claim_cost_is_flat_in_open_wait_wakes() -> None:
    conn = relay_connection()
    add_relay(conn, relay_id=RELAY_ID, machine_id=MACHINE_ID)
    _plant_relay_waits(conn, SMALL_PILE, 0)
    small = _relay_claim_statements(conn)
    _plant_relay_waits(conn, LARGE_PILE - SMALL_PILE, SMALL_PILE)
    large = _relay_claim_statements(conn)
    assert large == small
