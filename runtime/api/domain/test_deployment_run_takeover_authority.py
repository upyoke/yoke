"""While a steering seat covers the project, only its holder or the older
run's creating session may take over a driverless run waiting on item QA."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_deployment_run_target_takeover import (
    NEW,
    OLD,
    PASSED,
    WAITING,
    _close_passed,
    _contains,
    _members,
    _seed_new,
    _seed_old,
)
from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from runtime.api.fixtures.session_holdings import (
    insert_session,
    insert_steering_claim,
)
from yoke_core.domain.deployment_run_takeover_authority import (
    RESERVED_FOR_STEERING_CODE,
)
from yoke_core.domain.deployment_run_target_takeover import (
    TakeoverRefused,
    take_over_waiting_run,
)

STEERING = "covering-steering-session"
CREATOR = "older-run-creator"
WORKER = "unmandated-worker"


def _driverless_older_run(conn, monkeypatch, *, seat: bool) -> None:
    _seed_old(conn, run_qa=False)
    _close_passed(conn)
    release_seeded_driver(conn, OLD)
    row = conn.execute(
        "UPDATE deployment_runs SET created_by_session_id=%s WHERE id=%s "
        "RETURNING project_id",
        (CREATOR, OLD),
    ).fetchone()
    conn.commit()
    if seat:
        insert_session(conn, STEERING)
        insert_steering_claim(conn, STEERING, project_id=int(row["project_id"]))
    _seed_new(conn)
    _contains(monkeypatch)


@pytest.mark.parametrize("caller", [WORKER, None])
def test_another_session_is_refused_while_a_seat_covers_the_project(
    test_db, monkeypatch, caller
):
    _driverless_older_run(test_db, monkeypatch, seat=True)

    with pytest.raises(TakeoverRefused) as refused:
        take_over_waiting_run(test_db, NEW, session_id=caller)
    test_db.rollback()

    assert refused.value.code == RESERVED_FOR_STEERING_CODE
    message = str(refused.value)
    assert STEERING in message and CREATOR in message
    assert "yoke say --stdin --steering" in message
    assert _members(test_db, OLD) == {PASSED, WAITING}
    assert _members(test_db, NEW) == set()


@pytest.mark.parametrize("caller", [STEERING, CREATOR])
def test_the_seat_holder_and_the_creator_may_take_over(test_db, monkeypatch, caller):
    _driverless_older_run(test_db, monkeypatch, seat=True)

    assert take_over_waiting_run(test_db, NEW, session_id=caller) == OLD
    test_db.commit()

    assert _members(test_db, NEW) == {WAITING}


def test_without_a_covering_seat_any_session_may_take_over(test_db, monkeypatch):
    _driverless_older_run(test_db, monkeypatch, seat=False)

    assert take_over_waiting_run(test_db, NEW, session_id=WORKER) == OLD
    test_db.commit()

    assert _members(test_db, NEW) == {WAITING}
