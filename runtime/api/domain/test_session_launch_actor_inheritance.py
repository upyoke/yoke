"""A launched session acts for whoever started it, however many hops away."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain.session_launch_actor_inheritance import (
    LAUNCH_ACTOR_UNRESOLVED,
    resolve_launch_requester_actor,
)
from yoke_core.domain.sessions import SessionError
from yoke_core.domain.sessions_lifecycle_identity import resolve_session_actor_id
from runtime.api.domain.test_session_message_support import NOW_TEXT, message_connection


SEAT_ACTOR = 10
MACHINE_ACTOR = 11


def _record_launch(
    conn: sqlite3.Connection,
    *,
    launch_id: str,
    requester_actor_id: int,
) -> None:
    message_id = f"m-{launch_id}"
    conn.execute(
        "INSERT INTO session_messages ("
        "message_id,sender_actor_id,body,body_sha256,selector_snapshot,"
        "created_at,expires_at"
        ") VALUES (?,?,'go','sha','{}',?,?)",
        (message_id, requester_actor_id, NOW_TEXT, NOW_TEXT),
    )
    conn.execute(
        "INSERT INTO session_launches ("
        "launch_id,requester_actor_id,project_id,requested_surface,"
        "selected_surface,message_id,deadline_at,created_at"
        ") VALUES (?,?,1,'claude-cli','claude-cli',?,?,?)",
        (launch_id, requester_actor_id, message_id, NOW_TEXT, NOW_TEXT),
    )
    conn.commit()


def test_launch_binding_names_the_requesting_actor() -> None:
    conn = message_connection()
    _record_launch(conn, launch_id="L-1", requester_actor_id=SEAT_ACTOR)
    binding = resolve_launch_requester_actor(conn, "L-1")
    assert binding.bound is True
    assert binding.actor_id == SEAT_ACTOR


def test_registration_binds_the_launching_actor_over_the_machines_own() -> None:
    conn = message_connection()
    _record_launch(conn, launch_id="L-1", requester_actor_id=SEAT_ACTOR)
    # The machine running the worker would otherwise supply MACHINE_ACTOR.
    assert resolve_session_actor_id(conn, MACHINE_ACTOR, launch_id="L-1") == SEAT_ACTOR


def test_actor_inheritance_survives_two_launch_hops() -> None:
    conn = message_connection()
    # Hop one: the seat launches a worker on another machine.
    _record_launch(conn, launch_id="L-1", requester_actor_id=SEAT_ACTOR)
    first_hop = resolve_session_actor_id(conn, None, launch_id="L-1")
    assert first_hop == SEAT_ACTOR
    # Hop two: that worker launches its own session, requesting as the actor
    # it inherited — so the second worker binds the same seat.
    _record_launch(conn, launch_id="L-2", requester_actor_id=first_hop)
    assert resolve_session_actor_id(conn, MACHINE_ACTOR, launch_id="L-2") == SEAT_ACTOR


def test_an_unknown_launch_refuses_instead_of_binding_the_machine() -> None:
    conn = message_connection()
    binding = resolve_launch_requester_actor(conn, "L-missing")
    assert binding.bound is False
    assert binding.code == LAUNCH_ACTOR_UNRESOLVED
    with pytest.raises(SessionError) as refusal:
        resolve_session_actor_id(conn, MACHINE_ACTOR, launch_id="L-missing")
    assert refusal.value.code == LAUNCH_ACTOR_UNRESOLVED
    assert "yoke session-control launch get" in str(refusal.value)


def test_a_session_nobody_launched_still_binds_its_own_identity() -> None:
    conn = message_connection()
    assert resolve_session_actor_id(conn, MACHINE_ACTOR) == MACHINE_ACTOR


def test_the_hook_payload_carries_the_launch_id_into_registration() -> None:
    """The launch id reaches registration only through the launch channel."""
    from yoke_core.hooks.registration_observed import parse_hook_registration_facts

    import json as _json

    facts = parse_hook_registration_facts(
        _json.dumps(
            {
                "cwd": "/work",
                "yoke_launch": {"launch_id": " L-1 ", "attestation": "token"},
            }
        ),
        project_id=1,
        transcript_path="",
    )
    assert facts.launch_id == "L-1"

    unlaunched = parse_hook_registration_facts(
        _json.dumps({"cwd": "/work"}), project_id=1, transcript_path=""
    )
    assert unlaunched.launch_id == ""

    malformed = parse_hook_registration_facts(
        _json.dumps({"yoke_launch": "not-an-object"}),
        project_id=1,
        transcript_path="",
    )
    assert malformed.launch_id == ""
