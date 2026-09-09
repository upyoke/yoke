"""New item-bound launches refuse already-terminal work before any write."""

from __future__ import annotations

from copy import deepcopy

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definition
from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.session_launch_assignment import (
    assignment_session_name,
    refuse_terminal_assigned_item,
)
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
    launch_connection,
)


class _NoCloseConnection:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self) -> None:
        pass


def _request(payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="session.launch.create",
        actor=ActorContext(actor_id="1", session_id="caller"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _fleet_policy(_conn, _project_id, path: str):
    if path == "fleet.launch_deadline_minutes":
        return 10
    if path == "fleet.max_body_bytes":
        return 65536
    return False


def _pin_definition() -> dict:
    return deepcopy(builtin_workflow_definition("dash")["definition"])


def _archived_definition() -> dict:
    definition = _pin_definition()
    last = dict(definition["stages"][-1])
    last["id"] = "archived"
    definition["stages"] = [*definition["stages"][:-1], last]
    definition["terminal_stage_ids"] = ["archived"]
    return definition


def _seed_pinned_item(
    conn,
    *,
    status: str,
    workflow_id: str = "dash",
    definition: dict | None = None,
    sequence: int = 41,
) -> str:
    payload = definition if definition is not None else _pin_definition()
    conn.execute("ALTER TABLE projects ADD COLUMN org_id INTEGER DEFAULT 1")
    conn.execute("ALTER TABLE projects ADD COLUMN name TEXT DEFAULT 'Launch'")
    conn.execute("ALTER TABLE projects ADD COLUMN public_item_prefix TEXT")
    conn.execute("UPDATE projects SET public_item_prefix='LP' WHERE id=10")
    conn.execute(
        "CREATE TABLE workflow_versions ("
        "id INTEGER PRIMARY KEY, workflow_id TEXT NOT NULL, version INTEGER, "
        "definition_json TEXT NOT NULL, definition_digest TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE items ("
        "id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, "
        "project_sequence INTEGER NOT NULL, title TEXT, status TEXT NOT NULL, "
        "workflow_id TEXT NOT NULL, workflow_version_id INTEGER NOT NULL)"
    )
    conn.execute(
        "INSERT INTO workflow_versions "
        "(id, workflow_id, version, definition_json, definition_digest) "
        "VALUES (1, ?, 1, ?, ?)",
        (
            workflow_id,
            canonical_definition_json(payload),
            definition_digest(payload),
        ),
    )
    conn.execute(
        "INSERT INTO items "
        "(id, project_id, project_sequence, title, status, "
        "workflow_id, workflow_version_id) "
        "VALUES (41, 10, ?, 'Active launch target', ?, ?, 1)",
        (sequence, status, workflow_id),
    )
    conn.commit()
    return f"LP-{sequence}"


def _wire_create(monkeypatch, conn) -> None:
    monkeypatch.setattr(handlers, "_open", lambda: _NoCloseConnection(conn))
    monkeypatch.setattr(handlers, "_resolve_project", lambda _conn, _project: 10)
    monkeypatch.setattr(handlers, "_authorization", lambda *_a, **_k: authorization())
    monkeypatch.setattr(handlers, "_fleet_policy", _fleet_policy)
    monkeypatch.setattr("yoke_core.domain.session_launch_requests.utc_now", lambda: NOW)
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_surface_selection.utc_now",
        lambda: NOW,
    )


def _create_payload(item: str, *, compose_mandate: bool, key: str) -> dict:
    return {
        "project": "launch-project",
        "item": item,
        "executor_surface": "codex-cli",
        "instructions": "Custom full body." if not compose_mandate else "",
        "idempotency_key": key,
        "compose_mandate": compose_mandate,
    }


def _write_counts(conn) -> tuple[int, int, int]:
    launches = conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0]
    messages = conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0]
    attempts = conn.execute("SELECT COUNT(*) FROM session_launch_attempts").fetchone()[
        0
    ]
    return int(launches), int(messages), int(attempts)


def _create_conn(monkeypatch, *, status: str, definition: dict | None = None):
    conn = launch_connection()
    add_relay(conn, connected_until="2026-08-24T12:00:00Z")
    item = _seed_pinned_item(conn, status=status, definition=definition)
    _wire_create(monkeypatch, conn)
    return conn, item


@pytest.mark.parametrize(
    "status,compose_mandate",
    [
        ("cancelled", True),
        ("cancelled", False),
        ("stopped", True),
        ("stopped", False),
        ("done", True),
        ("done", False),
    ],
)
def test_terminal_create_refuses_before_any_write(monkeypatch, status, compose_mandate):
    conn, item = _create_conn(monkeypatch, status=status)
    before = _write_counts(conn)

    outcome = handlers.handle_launch_create(
        _request(_create_payload(item, compose_mandate=compose_mandate, key="term-1"))
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "assignment_item_terminal"
    assert "already terminal" in outcome.error.message
    assert _write_counts(conn) == before


def test_custom_workflow_terminal_stage_is_refused(monkeypatch):
    conn, item = _create_conn(
        monkeypatch, status="archived", definition=_archived_definition()
    )
    before = _write_counts(conn)

    outcome = handlers.handle_launch_create(
        _request(_create_payload(item, compose_mandate=False, key="archived-raw"))
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "assignment_item_terminal"
    assert _write_counts(conn) == before


@pytest.mark.parametrize("compose_mandate", [True, False])
def test_active_item_create_still_succeeds(monkeypatch, compose_mandate):
    conn, item = _create_conn(monkeypatch, status="idea")

    outcome = handlers.handle_launch_create(
        _request(
            _create_payload(item, compose_mandate=compose_mandate, key="active-ok")
        )
    )

    assert outcome.primary_success is True, outcome.error
    assert outcome.result_payload["deduplicated"] is False
    assert _write_counts(conn)[0] == 1


def test_same_request_idempotent_replay_returns_the_stored_launch(monkeypatch):
    conn, item = _create_conn(monkeypatch, status="idea")
    payload = _create_payload(item, compose_mandate=True, key="replay-1")

    first = handlers.handle_launch_create(_request(payload))
    second = handlers.handle_launch_create(_request(payload))

    assert first.primary_success is True
    assert second.primary_success is True
    assert second.result_payload["deduplicated"] is True
    assert (
        second.result_payload["launch"]["launch_id"]
        == first.result_payload["launch"]["launch_id"]
    )
    assert _write_counts(conn)[0] == 1


@pytest.mark.parametrize("compose_mandate", [True, False])
def test_changed_instructions_same_key_conflicts(monkeypatch, compose_mandate):
    conn, item = _create_conn(monkeypatch, status="idea")
    payload = _create_payload(
        item, compose_mandate=compose_mandate, key=f"changed-{compose_mandate}"
    )
    first = handlers.handle_launch_create(_request(payload))
    assert first.primary_success is True, first.error
    changed = {**payload, "instructions": "Different launch body."}
    second = handlers.handle_launch_create(_request(changed))
    assert second.primary_success is False
    assert second.error is not None
    assert second.error.code == "idempotency_conflict"
    assert _write_counts(conn)[0] == 1


@pytest.mark.parametrize("compose_mandate", [True, False])
def test_changed_instructions_still_conflict_after_item_is_terminal(
    monkeypatch, compose_mandate
):
    conn, item = _create_conn(monkeypatch, status="idea")
    payload = _create_payload(
        item, compose_mandate=compose_mandate, key=f"chg-term-{compose_mandate}"
    )
    first = handlers.handle_launch_create(_request(payload))
    assert first.primary_success is True, first.error
    conn.execute("UPDATE items SET status='cancelled' WHERE id=41")
    conn.commit()
    changed = {**payload, "instructions": "Different launch body."}
    second = handlers.handle_launch_create(_request(changed))
    assert second.primary_success is False
    assert second.error is not None
    assert second.error.code == "idempotency_conflict"
    assert _write_counts(conn)[0] == 1


@pytest.mark.parametrize("compose_mandate", [True, False])
def test_same_request_replay_survives_item_becoming_terminal(
    monkeypatch, compose_mandate
):
    conn, item = _create_conn(monkeypatch, status="idea")
    payload = _create_payload(
        item, compose_mandate=compose_mandate, key=f"replay-term-{compose_mandate}"
    )
    first = handlers.handle_launch_create(_request(payload))
    assert first.primary_success is True, first.error
    conn.execute("UPDATE items SET status='cancelled' WHERE id=41")
    conn.commit()
    second = handlers.handle_launch_create(_request(payload))
    assert second.primary_success is True, second.error
    assert second.result_payload["deduplicated"] is True
    assert (
        second.result_payload["launch"]["launch_id"]
        == first.result_payload["launch"]["launch_id"]
    )
    assert _write_counts(conn)[0] == 1


def test_assignment_name_still_names_a_terminal_item():
    conn = launch_connection()
    item = _seed_pinned_item(conn, status="archived", definition=_archived_definition())
    assert assignment_session_name(conn, public_ref=item, project_id=10) == (
        "LP-41: Active launch target"
    )


def test_refuse_terminal_uses_typed_stage_membership():
    conn = launch_connection()
    item = _seed_pinned_item(conn, status="archived", definition=_archived_definition())
    with pytest.raises(SessionLaunchError) as raised:
        refuse_terminal_assigned_item(conn, public_ref=item, project_id=10)
    assert raised.value.code == "assignment_item_terminal"
