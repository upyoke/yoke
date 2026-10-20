"""Launch lists name the item each launch staffs and filter by it."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import item_ref_resolution, project_identity
from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.session_launch_assignment import assignment_ref
from yoke_core.domain.session_launch_history_page import read_launch_page
from runtime.api.domain.session_launch_test_support import (
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)
from runtime.api.domain.test_session_launch_history_page import _NoCloseConnection


def _named(conn, key: str, session_name: str | None, state: str) -> str:
    launch = assigned_launch(conn, key=key)
    conn.execute(
        "UPDATE session_launches SET session_name=?, state=? WHERE launch_id=?",
        (session_name, state, launch.launch_id),
    )
    conn.commit()
    return launch.launch_id


def _seeded():
    conn = launch_connection()
    add_relay(conn)
    ids = {
        "staffed": _named(conn, "a", "YOK-12: Fix the thing", "succeeded"),
        "live": _named(conn, "b", "YOK-12: Fix the thing", "queued"),
        "longer": _named(conn, "c", "YOK-120: Other work", "succeeded"),
        "free": _named(conn, "d", None, "succeeded"),
    }
    return conn, ids


def test_assignment_ref_reads_the_prefix_ahead_of_the_colon() -> None:
    assert assignment_ref("YOK-12: Fix the thing") == "YOK-12"
    assert assignment_ref("free-form name") == ""
    assert assignment_ref(None) == ""


def test_item_filter_keeps_only_launches_staffing_that_item() -> None:
    conn, ids = _seeded()
    page = read_launch_page(conn, project_id=10, item="YOK-12")
    assert [row["launch_id"] for row in page["operational"]] == [ids["live"]]
    assert [row["launch_id"] for row in page["history"]] == [ids["staffed"]]
    assert page["history_matched_count"] == 1
    assert {row["item"] for row in page["history"]} == {"YOK-12"}


def test_unfiltered_rows_carry_item_and_session_name() -> None:
    conn, ids = _seeded()
    rows = {
        row["launch_id"]: row
        for row in read_launch_page(conn, project_id=10)["history"]
    }
    assert rows[ids["longer"]]["item"] == "YOK-120"
    assert rows[ids["longer"]]["session_name"] == "YOK-120: Other work"
    assert rows[ids["free"]]["item"] is None


def _list(monkeypatch, conn, item: str):
    monkeypatch.setattr(handlers, "_open", lambda: _NoCloseConnection(conn))
    monkeypatch.setattr(handlers, "_resolve_project", lambda _conn, _project: 10)
    monkeypatch.setattr(
        handlers,
        "launch_authorization",
        lambda _conn, _request, _project_id: authorization(operator=True),
    )
    return handlers.handle_launch_list(
        FunctionCallRequest(
            function="session_control.launch.list",
            actor=ActorContext(actor_id="1", session_id="caller"),
            target=TargetRef(kind="global"),
            payload={"project": "yoke", "item": item},
        )
    )


def test_handler_filters_by_the_canonical_item_ref(monkeypatch) -> None:
    conn, ids = _seeded()
    monkeypatch.setattr(
        item_ref_resolution, "resolve_item_ref_or_none", lambda *_a, **_k: 12
    )
    monkeypatch.setattr(project_identity, "render_item_ref", lambda *_a, **_k: "YOK-12")
    outcome = _list(monkeypatch, conn, "yok-12")
    assert outcome.primary_success, outcome.error
    assert [row["launch_id"] for row in outcome.result_payload["history"]] == [
        ids["staffed"]
    ]


def test_handler_refuses_an_item_outside_the_project(monkeypatch) -> None:
    conn, _ids = _seeded()
    monkeypatch.setattr(
        item_ref_resolution, "resolve_item_ref_or_none", lambda *_a, **_k: None
    )
    outcome = _list(monkeypatch, conn, "YOK-99999")
    assert not outcome.primary_success
    assert outcome.error.code == "item_not_found"
    assert "YOK-99999" in outcome.error.message
