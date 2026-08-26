"""A relay roster names the person whose machine each card describes."""

from __future__ import annotations

import json

from yoke_core.domain.session_relay_read import list_visible_relays
from runtime.api.domain.test_session_message_support import message_connection


def _relay(conn, relay_id: str, actor_id: int, hostname: str) -> None:
    conn.execute(
        "INSERT INTO session_relays (relay_id,actor_id,machine_id,hostname,"
        "relay_version,surface_versions,project_checkouts,first_seen_at,"
        "last_seen_at,connected_until,state) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            relay_id,
            actor_id,
            "11111111-1111-4111-8111-111111111111",
            hostname,
            "launch.271",
            json.dumps({"codex-desktop": "26.814"}),
            json.dumps([1]),
            "2026-08-22T12:00:00Z",
            "2026-08-22T12:01:00Z",
            "2026-08-22T12:03:00Z",
            "active",
        ),
    )
    conn.commit()


def test_each_card_names_its_owner_without_exposing_the_actor_id() -> None:
    # Relays are visible to everyone who shares one of their projects, so a
    # roster that only knows machine ids cannot tell two teammates apart.
    conn = message_connection()
    _relay(conn, "machine:ada", 10, "ada-studio")
    _relay(conn, "machine:grace", 11, "grace-laptop")

    relays = list_visible_relays(conn, actor_id=10, now="2026-08-22T12:02:00Z")

    owners = {relay["hostname"]: relay["owner"] for relay in relays}
    assert owners == {"ada-studio": "Ada", "grace-laptop": "Grace"}
    assert all("actor_id" not in relay for relay in relays)


def test_an_owner_without_a_display_label_leaves_the_field_empty() -> None:
    # Actor 12 exists but carries no label on any surface. An unnamed owner
    # renders as "no owner recorded" rather than failing the whole roster.
    conn = message_connection()
    _relay(conn, "machine:unlabelled", 12, "spare-box")

    relays = list_visible_relays(conn, actor_id=10, now="2026-08-22T12:02:00Z")

    assert [relay["owner"] for relay in relays] == [""]


def test_owner_resolution_is_one_lookup_per_owner_not_one_per_relay() -> None:
    # A machine roster holds many more relays than distinct owners, and the
    # page renders every visible one at once.
    conn = message_connection()
    for index in range(6):
        _relay(conn, f"machine:ada-{index}", 10, f"ada-{index}")

    executed: list[str] = []
    conn.set_trace_callback(executed.append)
    try:
        relays = list_visible_relays(conn, actor_id=10, now="2026-08-22T12:02:00Z")
    finally:
        conn.set_trace_callback(None)

    assert len(relays) == 6
    assert {relay["owner"] for relay in relays} == {"Ada"}
    assert sum("actor_labels" in sql for sql in executed) == 1
