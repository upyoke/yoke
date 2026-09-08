"""Launch paging keeps every actionable launch visible and its counts honest."""

from __future__ import annotations

import sqlite3

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.session_launch_history_page import (
    OPERATIONAL_LAUNCH_STATES,
    read_launch_page,
)
from yoke_core.domain.session_launch_types import SessionLaunchError
from runtime.api.domain.session_launch_test_support import (
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)

import pytest


class _NoCloseConnection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def close(self) -> None:
        pass


def _seed(
    conn: sqlite3.Connection,
    *,
    key: str,
    state: str,
    created_at: str,
    surface: str = "codex-cli",
    machine_id: str = "machine-1",
) -> str:
    # Created on the fixture relay's own surface, then stamped with the state,
    # surface, and machine this row is meant to represent: eligibility is the
    # create path's subject, not this one's.
    launch = assigned_launch(conn, key=key)
    conn.execute(
        "UPDATE session_launches SET state=?, created_at=?, requested_surface=?, "
        "selected_surface=?, assigned_machine_id=? WHERE launch_id=?",
        (state, created_at, surface, surface, machine_id, launch.launch_id),
    )
    conn.commit()
    return launch.launch_id


def _stamp(index: int) -> str:
    return f"2026-08-{index:02d}T12:00:00Z"


def _request(payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="session_control.launch.list",
        actor=ActorContext(actor_id="1", session_id="caller"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _wire(monkeypatch, conn, *, operator: bool = True) -> None:
    monkeypatch.setattr(handlers, "_open", lambda: _NoCloseConnection(conn))
    monkeypatch.setattr(handlers, "_resolve_project", lambda _conn, _project: 10)
    monkeypatch.setattr(
        handlers,
        "_authorization",
        lambda _conn, _request, _project_id: authorization(operator=operator),
    )


def _ids(rows) -> list[str]:
    return [row["launch_id"] for row in rows]


def test_operational_states_cover_unfinished_and_actionable_launches() -> None:
    assert OPERATIONAL_LAUNCH_STATES == {
        "queued",
        "assigned",
        "launching",
        "awaiting_registration",
        "expired",
        "failed",
        "outcome_unknown",
    }


def test_an_old_actionable_launch_survives_a_full_history_window() -> None:
    conn = launch_connection()
    add_relay(conn)
    stranded = _seed(
        conn, key="stranded", state="outcome_unknown", created_at=_stamp(1)
    )
    for index in range(2, 10):
        _seed(conn, key=f"done-{index}", state="succeeded", created_at=_stamp(index))

    page = read_launch_page(conn, project_id=10, limit=3)

    # Eight completed launches are newer than the stranded one, so any
    # newest-first window would have buried it.
    assert _ids(page["operational"]) == [stranded]
    assert page["operational_count"] == 1
    assert len(page["history"]) == 3
    assert page["history_matched_count"] == 8
    assert page["next_cursor"]


def test_history_pages_forward_without_gaps_or_duplicates() -> None:
    conn = launch_connection()
    add_relay(conn)
    seeded = [
        _seed(conn, key=f"done-{index}", state="succeeded", created_at=_stamp(index))
        for index in range(1, 8)
    ]
    newest_first = list(reversed(seeded))

    first = read_launch_page(conn, project_id=10, limit=3)
    second = read_launch_page(
        conn, project_id=10, limit=3, cursor=first["next_cursor"]
    )
    # A newer launch arrives between pages. An offset would skip a row here and
    # a positional window would repeat one; a cursor naming a position does
    # neither, and the new row simply is not in this walk.
    late = _seed(conn, key="late", state="succeeded", created_at=_stamp(9))
    third = read_launch_page(
        conn, project_id=10, limit=3, cursor=second["next_cursor"]
    )

    paged = [*_ids(first["history"]), *_ids(second["history"]), *_ids(third["history"])]
    assert paged == newest_first
    assert late not in paged
    assert third["next_cursor"] is None
    # A continuation carries completed history alone; the caller already holds
    # the operational rows from its first request.
    assert second["operational"] == []
    assert second["operational_count"] == 0


def test_criteria_apply_before_selection_and_before_counting() -> None:
    conn = launch_connection()
    add_relay(conn)
    kept = _seed(
        conn,
        key="kept",
        state="failed",
        created_at=_stamp(3),
        surface="claude-cli",
        machine_id="machine-2",
    )
    _seed(conn, key="other-surface", state="failed", created_at=_stamp(4))
    _seed(
        conn,
        key="other-machine",
        state="succeeded",
        created_at=_stamp(5),
        surface="claude-cli",
        machine_id="machine-3",
    )

    page = read_launch_page(
        conn, project_id=10, surface="claude-cli", machine="machine-2"
    )

    assert _ids(page["operational"]) == [kept]
    assert page["operational_count"] == 1
    assert page["history"] == []
    assert page["history_matched_count"] == 0


def test_state_criterion_narrows_both_sets() -> None:
    conn = launch_connection()
    add_relay(conn)
    failed = _seed(conn, key="failed", state="failed", created_at=_stamp(3))
    _seed(conn, key="expired", state="expired", created_at=_stamp(4))
    _seed(conn, key="succeeded", state="succeeded", created_at=_stamp(5))

    page = read_launch_page(conn, project_id=10, state="failed")

    assert _ids(page["operational"]) == [failed]
    assert page["operational_count"] == 1
    assert page["history_matched_count"] == 0


def test_an_unreadable_cursor_names_how_to_recover() -> None:
    conn = launch_connection()
    add_relay(conn)

    with pytest.raises(SessionLaunchError) as refusal:
        read_launch_page(conn, project_id=10, cursor="not-a-cursor")

    assert refusal.value.code == "cursor_invalid"
    assert "load the first history page again" in str(refusal.value)


def test_list_rows_carry_their_project_label(monkeypatch) -> None:
    conn = launch_connection()
    add_relay(conn)
    _seed(conn, key="labelled", state="succeeded", created_at=_stamp(3))
    _wire(monkeypatch, conn)

    outcome = handlers.handle_launch_list(_request({"project": "launch-project"}))

    assert outcome.primary_success
    assert [row["project"] for row in outcome.result_payload["history"]] == [
        "launch-project"
    ]


def test_listing_still_requires_project_operator_permission(monkeypatch) -> None:
    conn = launch_connection()
    add_relay(conn)
    _seed(conn, key="guarded", state="succeeded", created_at=_stamp(3))
    _wire(monkeypatch, conn, operator=False)

    outcome = handlers.handle_launch_list(_request({"project": "launch-project"}))

    assert outcome.primary_success is False
    assert outcome.error and outcome.error.code == "permission_denied"
