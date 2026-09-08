"""Machine registration and project authority at the relay boundary."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.actor_permissions import ROLE_OPERATOR, grant_actor_project_role
from yoke_core.domain.handlers import session_relay as relay_handlers
from yoke_core.domain.handlers.session_relay_idle_hosts import handle_relay_idle_hosts
from runtime.api.domain.session_relay_handler_test_support import (
    NoCloseConnection,
    claim_payload,
    relay_request,
)
from runtime.api.domain.test_session_message_support import message_connection


MACHINE_ID = "11111111-1111-4111-8111-111111111111"


def _register_machine(conn, *, owner_actor_id: int) -> None:
    from yoke_core.domain.machine_registry import register_machine
    from yoke_core.domain.machine_registry_schema import ensure_machine_registry_schema

    ensure_machine_registry_schema(conn)
    register_machine(
        conn,
        machine_id=MACHINE_ID,
        name="host-1",
        actor_id=owner_actor_id,
        now="2026-08-22T12:00:00Z",
    )


def _bind_connection(monkeypatch, conn) -> None:
    from yoke_core.domain import db_helpers

    monkeypatch.setattr(db_helpers, "connect", lambda: NoCloseConnection(conn))


def _claim(*, projects: list[int], actor_id: str):
    payload = claim_payload()
    payload["projects"] = projects
    return relay_handlers.handle_relay_claim(
        relay_request("session_control.relay.claim", payload, actor_id=actor_id)
    )


def test_claim_refuses_cross_project_advertisement_before_heartbeat(
    monkeypatch,
) -> None:
    conn = message_connection()
    _register_machine(conn, owner_actor_id=13)
    grant_actor_project_role(conn, actor_id=13, project_id=1, role_name=ROLE_OPERATOR)
    _bind_connection(monkeypatch, conn)

    outcome = _claim(projects=[1, 2], actor_id="13")

    assert outcome.primary_success is False
    assert outcome.error and outcome.error.code == "permission_denied"
    assert conn.execute("SELECT COUNT(*) FROM session_relays").fetchone()[0] == 0


def test_authorized_claim_stamps_actor_and_only_advertised_projects(
    monkeypatch,
) -> None:
    conn = message_connection()
    _register_machine(conn, owner_actor_id=13)
    grant_actor_project_role(conn, actor_id=13, project_id=1, role_name=ROLE_OPERATOR)
    _bind_connection(monkeypatch, conn)

    outcome = _claim(projects=[1], actor_id="13")

    assert outcome.primary_success is True
    row = conn.execute(
        "SELECT actor_id,project_checkouts FROM session_relays WHERE relay_id='relay-1'"
    ).fetchone()
    assert row["actor_id"] == 13
    assert json.loads(row["project_checkouts"]) == [1]


def test_in_process_relay_refuses_a_retired_registered_machine(monkeypatch) -> None:
    conn = message_connection()
    _register_machine(conn, owner_actor_id=13)
    conn.execute(
        "UPDATE machines SET retired_at='2026-08-22T12:01:00Z' WHERE machine_id=?",
        (MACHINE_ID,),
    )
    grant_actor_project_role(conn, actor_id=13, project_id=1, role_name=ROLE_OPERATOR)
    _bind_connection(monkeypatch, conn)

    outcome = _claim(projects=[1], actor_id="13")

    assert outcome.primary_success is False
    assert outcome.error and outcome.error.code == "machine_retired"
    assert conn.execute("SELECT COUNT(*) FROM session_relays").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("function_id", "handler", "payload"),
    [
        (
            "session_control.relay.turn_end",
            relay_handlers.handle_relay_turn_end,
            {
                "relay_id": "relay-1",
                "machine_id": MACHINE_ID,
                "projects": [1],
                "turn_ends": [],
            },
        ),
        (
            "session_control.relay.liveness",
            relay_handlers.handle_relay_liveness,
            {
                "relay_id": "relay-1",
                "machine_id": MACHINE_ID,
                "projects": [1],
                "sessions": [],
                "launches": [],
            },
        ),
        (
            "session_control.relay.idle_hosts",
            handle_relay_idle_hosts,
            {
                "relay_id": "relay-1",
                "machine_id": MACHINE_ID,
                "projects": [1],
                "hosts": [],
                "reclaimed": [],
            },
        ),
        (
            "session_control.relay.report",
            relay_handlers.handle_relay_report,
            {
                "relay_id": "relay-1",
                "machine_id": MACHINE_ID,
                "job_kind": "wake",
                "job_id": "job-1",
                "lease_id": "lease-1",
                "result": "accepted",
            },
        ),
    ],
)
def test_retired_machine_refuses_every_relay_lifecycle_operation(
    monkeypatch, function_id, handler, payload
) -> None:
    conn = message_connection()
    _register_machine(conn, owner_actor_id=13)
    conn.execute(
        "UPDATE machines SET retired_at='2026-08-22T12:01:00Z' WHERE machine_id=?",
        (MACHINE_ID,),
    )
    grant_actor_project_role(conn, actor_id=13, project_id=1, role_name=ROLE_OPERATOR)
    _bind_connection(monkeypatch, conn)

    outcome = handler(relay_request(function_id, payload, actor_id="13"))

    assert outcome.primary_success is False
    assert outcome.error and outcome.error.code == "machine_retired"


def test_claim_refuses_viewer_advertisement(monkeypatch) -> None:
    conn = message_connection()
    _register_machine(conn, owner_actor_id=11)
    _bind_connection(monkeypatch, conn)

    outcome = _claim(projects=[1], actor_id="11")

    assert outcome.primary_success is False
    assert outcome.error and outcome.error.code == "permission_denied"
    assert conn.execute("SELECT COUNT(*) FROM session_relays").fetchone()[0] == 0
