"""A permitted machine reaches the roster before it records any checkout."""

from __future__ import annotations

import json

from yoke_contracts.machine_config import machine_access
from yoke_core.domain import machine_registry
from yoke_core.domain.session_relay_read import list_visible_relays
from runtime.api.domain.test_session_message_support import message_connection


FRESH_MACHINE = "33333333-3333-4333-8333-333333333333"
SETTLED_MACHINE = "44444444-4444-4444-8444-444444444444"
NOW = "2026-08-22T12:02:00Z"

#: Actor ids seeded by ``message_connection``: 10 operates projects 1 and 2,
#: 11 only views them, 12 administers the org, 13 belongs to nothing.
OPERATOR = 10
VIEWER = 11
ADMIN = 12
OUTSIDER = 13


def _relay(
    conn,
    relay_id: str,
    *,
    machine_id: str,
    actor_id: int,
    hostname: str,
    checkouts: list[int],
) -> None:
    conn.execute(
        "INSERT INTO session_relays (relay_id,actor_id,machine_id,hostname,"
        "relay_version,surface_versions,project_checkouts,first_seen_at,"
        "last_seen_at,connected_until,state,relay_health,surface_plan_limits) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            relay_id,
            actor_id,
            machine_id,
            hostname,
            "launch.271",
            json.dumps({"claude-cli": "2.1.261"}),
            json.dumps(checkouts),
            "2026-08-22T12:00:00Z",
            "2026-08-22T12:01:00Z",
            "2026-08-22T12:03:00Z",
            "active",
            json.dumps({"poll": {"state": "ok"}}),
            json.dumps({"claude-cli": {"plan": "max", "resets_at": NOW}}),
        ),
    )
    conn.commit()


def _register(conn, machine_id: str, *, owner: int, access=None) -> None:
    machine_registry.register_machine(
        conn,
        machine_id=machine_id,
        name=f"machine-{machine_id[:4]}",
        actor_id=owner,
        access=access,
        now="2026-08-22T11:00:00Z",
    )


def _hostnames(relays) -> set[str]:
    return {relay["hostname"] for relay in relays}


def test_a_machine_the_actor_owns_is_visible_before_any_checkout_exists() -> None:
    # The reported defect: a relay connects, records no project checkout yet,
    # and its own owner cannot see the machine they just plugged in.
    conn = message_connection()
    _register(conn, FRESH_MACHINE, owner=OPERATOR)
    _relay(
        conn,
        "relay:fresh",
        machine_id=FRESH_MACHINE,
        actor_id=OPERATOR,
        hostname="fresh-mac",
        checkouts=[],
    )

    relays = list_visible_relays(conn, actor_id=OPERATOR, now=NOW)

    assert _hostnames(relays) == {"fresh-mac"}
    assert relays[0]["project_ids"] == []


def test_an_administrator_sees_a_teammates_checkoutless_machine() -> None:
    # ``owner_only`` is the registered default, and an administrator is exactly
    # who is asked to diagnose a machine that has connected but done no work.
    conn = message_connection()
    _register(conn, FRESH_MACHINE, owner=OPERATOR)
    _relay(
        conn,
        "relay:fresh",
        machine_id=FRESH_MACHINE,
        actor_id=OPERATOR,
        hostname="fresh-mac",
        checkouts=[],
    )

    relays = list_visible_relays(conn, actor_id=ADMIN, now=NOW)

    assert _hostnames(relays) == {"fresh-mac"}


def test_a_checkoutless_machine_stays_hidden_from_an_actor_it_refuses() -> None:
    # Visibility is authorization, not decoration: an ``owner_only`` machine
    # with nothing shared to intersect admits nobody else.
    conn = message_connection()
    _register(conn, FRESH_MACHINE, owner=OPERATOR)
    _relay(
        conn,
        "relay:fresh",
        machine_id=FRESH_MACHINE,
        actor_id=OPERATOR,
        hostname="fresh-mac",
        checkouts=[],
    )

    assert list_visible_relays(conn, actor_id=VIEWER, now=NOW) == []
    assert list_visible_relays(conn, actor_id=OUTSIDER, now=NOW) == []


def test_an_access_document_that_names_an_actor_admits_that_actor() -> None:
    # The access document is the authority; the roster reads it rather than
    # carrying a second rule of its own.
    conn = message_connection()
    _register(
        conn,
        FRESH_MACHINE,
        owner=OPERATOR,
        access={"use": {"mode": machine_access.USE_ACTORS, "actor_ids": [VIEWER]}},
    )
    _relay(
        conn,
        "relay:fresh",
        machine_id=FRESH_MACHINE,
        actor_id=OPERATOR,
        hostname="fresh-mac",
        checkouts=[],
    )

    assert _hostnames(list_visible_relays(conn, actor_id=VIEWER, now=NOW)) == {
        "fresh-mac"
    }
    assert list_visible_relays(conn, actor_id=OUTSIDER, now=NOW) == []


def test_an_unregistered_machine_stays_visible_through_its_shared_checkout() -> None:
    # A relay that predates machine registration still serves a project this
    # actor can see, and that has always been its own ground for a card.
    conn = message_connection()
    _relay(
        conn,
        "relay:settled",
        machine_id=SETTLED_MACHINE,
        actor_id=VIEWER,
        hostname="settled-mini",
        checkouts=[2],
    )

    relays = list_visible_relays(conn, actor_id=OPERATOR, now=NOW)

    assert _hostnames(relays) == {"settled-mini"}
    assert relays[0]["project_ids"] == [2]


def test_the_project_filter_still_answers_which_machines_serve_that_project():
    # Filtering by project asks which machines carry that checkout, so a
    # permitted machine with no checkout at all is not one of them.
    conn = message_connection()
    _register(conn, FRESH_MACHINE, owner=OPERATOR)
    _relay(
        conn,
        "relay:fresh",
        machine_id=FRESH_MACHINE,
        actor_id=OPERATOR,
        hostname="fresh-mac",
        checkouts=[],
    )
    _relay(
        conn,
        "relay:settled",
        machine_id=SETTLED_MACHINE,
        actor_id=OPERATOR,
        hostname="settled-mini",
        checkouts=[2],
    )

    relays = list_visible_relays(conn, actor_id=OPERATOR, project="beta", now=NOW)

    assert _hostnames(relays) == {"settled-mini"}


def test_a_checkoutless_machine_still_carries_its_health_and_quota_facts():
    # The card is only worth showing if it says what the machine is doing, so
    # the projection must not degrade for a machine with no checkout.
    conn = message_connection()
    _register(conn, FRESH_MACHINE, owner=OPERATOR)
    _relay(
        conn,
        "relay:fresh",
        machine_id=FRESH_MACHINE,
        actor_id=OPERATOR,
        hostname="fresh-mac",
        checkouts=[],
    )

    relay = list_visible_relays(conn, actor_id=OPERATOR, now=NOW)[0]

    assert relay["liveness"] == "connected"
    assert relay["surface_versions"] == {"claude-cli": "2.1.261"}
    assert relay["relay_health"]
    assert relay["plan_limits"]
    assert relay["capacity"]["machine_id"] == FRESH_MACHINE
