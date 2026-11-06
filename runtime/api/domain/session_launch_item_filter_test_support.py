# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.handlers import session_launch as handlers


from yoke_core.domain.session_launch_history_page import read_launch_page

from runtime.api.domain.session_launch_test_support import (
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)

from runtime.api.domain.session_launch_history_page_test_support import _NoCloseConnection

def _named(conn, key: str, item_id: int | None, state: str) -> str:
    launch = assigned_launch(conn, key=key)
    conn.execute(
        "UPDATE session_launches SET item_id=?, state=? WHERE launch_id=?",
        (item_id, state, launch.launch_id),
    )
    conn.commit()
    return launch.launch_id

def _seeded():
    conn = launch_connection()
    conn.executescript(
        """
        ALTER TABLE projects ADD COLUMN name TEXT NOT NULL DEFAULT '';
        ALTER TABLE projects ADD COLUMN public_item_prefix TEXT;
        UPDATE projects SET name='Launch project', public_item_prefix='YOK'
        WHERE id=10;
        INSERT INTO projects (id, slug, name, public_item_prefix)
        VALUES (20, 'other-project', 'Other project', 'OTHER');
        DROP TABLE items;
        CREATE TABLE items (
            id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL,
            project_sequence INTEGER NOT NULL
        );
        INSERT INTO items (id, project_id, project_sequence)
        VALUES (312, 10, 12), (420, 10, 120), (999, 20, 99999);
        """
    )
    add_relay(conn)
    ids = {
        "staffed": _named(conn, "a", 312, "succeeded"),
        "live": _named(conn, "b", 312, "queued"),
        "longer": _named(conn, "c", 420, "succeeded"),
        "free": _named(conn, "d", None, "succeeded"),
    }
    return conn, ids

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

def exercise_canonical_item_filter(monkeypatch) -> None:
    conn, ids = _seeded()
    outcome = _list(monkeypatch, conn, "yok-12")
    assert outcome.primary_success, outcome.error
    assert [row["launch_id"] for row in outcome.result_payload["history"]] == [
        ids["staffed"]
    ]

def exercise_foreign_item_filter(monkeypatch) -> None:
    conn, _ids = _seeded()
    outcome = _list(monkeypatch, conn, "YOK-99999")
    assert not outcome.primary_success
    assert outcome.error.code == "item_not_found"
    assert "YOK-99999" in outcome.error.message
