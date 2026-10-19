"""A run's close-out never holds a transaction open across file-system work.

Lane retirement and the checkout sweep can take minutes per member. Every
database connection the close-out opened must sit idle, not idle in a
transaction, while that work runs; otherwise the server ends the session
and every later member's effects fail on a closed connection. A connection
that drops during one member's effects is reopened, and the members after
it still finish.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg

from runtime.api.domain.test_run_success_member_settlement import _run, _status
from runtime.api.domain.test_shared_gate_two_phase_settlement import (
    MEMBERS,
    _executing_run,
    _five_ready_members,
)
from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from yoke_core.domain import delivery_member_close_effects as close_effects
from yoke_core.domain import terminal_lane_cleanup
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.project_identity import render_item_ref

DROPPED = "consuming input failed: server closed the connection unexpectedly"


def _open_transactions(test_db: Any) -> list[str]:
    """Other backends on this database left idle inside a transaction."""
    observer = connect()
    try:
        rows = observer.execute(
            "SELECT pid, state, query FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid() "
            "AND pid <> %s AND state LIKE 'idle in transaction%%'",
            (test_db.info.backend_pid,),
        ).fetchall()
        observer.commit()
    finally:
        observer.close()
    return [f"{row['pid']} {row['state']}: {row['query']}" for row in rows]


def test_slow_lane_work_runs_with_every_connection_idle(
    test_db: Any, monkeypatch, tmp_path: Path
) -> None:
    _isolate_status_effects(monkeypatch)
    _five_ready_members(test_db)
    _executing_run(test_db, "run-idle-lanes")
    observed: list[list[str]] = []

    def _retire(item, envelope, **_kwargs):
        raise AssertionError("a run member's lanes retire only through the sweep")

    def _sweep(**_kwargs):
        observed.append(_open_transactions(test_db))
        return (), {}

    monkeypatch.setattr(
        terminal_lane_cleanup, "record_terminal_lane_close_out", _retire
    )
    monkeypatch.setattr(terminal_lane_cleanup, "sweep_managed_lanes", _sweep)
    monkeypatch.setattr(
        terminal_lane_cleanup, "checkout_for_project_id", lambda _id: tmp_path
    )

    assert cmd_update("run-idle-lanes", "status", "succeeded") is None

    assert observed == [[]]
    assert _run(test_db, "run-idle-lanes") == ("succeeded", True)


def _drop_once_for(item_ids: set[int], monkeypatch) -> list[int]:
    """Drop the session step's connection once per listed member."""
    real = close_effects._end_previous_claim_holders_if_empty
    calls: list[int] = []

    def _step(conn, *, item_id: int) -> None:
        calls.append(int(item_id))
        if int(item_id) in item_ids:
            item_ids.discard(int(item_id))
            raise psycopg.OperationalError(DROPPED)
        real(conn, item_id=item_id)

    monkeypatch.setattr(close_effects, "_end_previous_claim_holders_if_empty", _step)
    return calls


def test_a_dropped_connection_is_reopened_and_the_run_finishes(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _five_ready_members(test_db)
    _executing_run(test_db, "run-reconnect")
    monkeypatch.setattr(
        terminal_lane_cleanup, "record_terminal_lane_close_out", lambda *a, **k: None
    )
    calls = _drop_once_for({MEMBERS[1]}, monkeypatch)

    assert cmd_update("run-reconnect", "status", "succeeded") is None

    assert sorted(calls) == sorted([*MEMBERS, MEMBERS[1]])
    assert _run(test_db, "run-reconnect") == ("succeeded", True)
    for item_id in MEMBERS:
        assert _status(test_db, item_id) == "done"


def test_a_connection_that_stays_down_costs_only_its_own_member(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _five_ready_members(test_db)
    _executing_run(test_db, "run-lost-member")
    monkeypatch.setattr(
        terminal_lane_cleanup, "record_terminal_lane_close_out", lambda *a, **k: None
    )
    lost = MEMBERS[1]
    real = close_effects._end_previous_claim_holders_if_empty
    finished: list[int] = []

    def _step(conn, *, item_id: int) -> None:
        if int(item_id) == lost:
            raise psycopg.OperationalError(DROPPED)
        real(conn, item_id=item_id)
        finished.append(int(item_id))

    monkeypatch.setattr(close_effects, "_end_previous_claim_holders_if_empty", _step)

    refusal = cmd_update("run-lost-member", "status", "succeeded")

    assert refusal is not None
    lost_ref = render_item_ref(test_db, lost)
    assert f"{lost_ref}: its post-close effects did not finish" in refusal
    assert DROPPED in refusal
    for item_id in MEMBERS:
        if item_id != lost:
            assert render_item_ref(test_db, item_id) not in refusal
    assert sorted(finished) == sorted(m for m in MEMBERS if m != lost)
    assert _run(test_db, "run-lost-member") == ("executing", True)

    monkeypatch.setattr(close_effects, "_end_previous_claim_holders_if_empty", real)
    assert cmd_update("run-lost-member", "status", "succeeded") is None
    assert _run(test_db, "run-lost-member") == ("succeeded", True)
